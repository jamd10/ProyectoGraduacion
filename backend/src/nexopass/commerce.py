"""Compra simulada y boletos: importes de servidor, inventario transaccional."""
import base64
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
import json
import secrets
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field, SecretStr, model_validator
from sqlalchemy import select, update, func, exists, and_, delete
from sqlalchemy.dialects.postgresql import insert
import qrcode

from nexopass import schema as s
from nexopass.security import db, current_user, verified_user, admin_user, cipher, digest, now, audit, limited, roles_for
from nexopass.mail import queue_mail

router = APIRouter(prefix="/api/v1", tags=["Tickets"])


class ReserveInput(BaseModel):
    event_id: UUID
    zone_id: UUID
    unit_ids: list[UUID] = Field(default_factory=list, max_length=6)
    quantity: int = Field(default=1, ge=1, le=6)


class Attendee(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    document_type: Literal["DNI", "PASSPORT", "OTHER"] = "DNI"
    document_number: SecretStr = Field(min_length=4, max_length=40)


class CheckoutInput(BaseModel):
    idempotency_key: UUID
    attendees: list[Attendee] = Field(min_length=1, max_length=6)
    method: Literal["card_demo", "crypto_demo"] = "card_demo"
    result: Literal["approved", "rejected", "pending"] = "approved"
    card_number: SecretStr | None = None
    card_holder: str = Field(default="", max_length=200)
    expiry: str = Field(default="", max_length=5)
    cvv: SecretStr | None = None

    @model_validator(mode="after")
    def card(self):
        if self.method == "card_demo":
            number = self.card_number.get_secret_value().replace(" ", "") if self.card_number else ""
            cvv = self.cvv.get_secret_value() if self.cvv else ""
            import re
            if not (number.isdigit() and 13 <= len(number) <= 19 and cvv.isdigit() and len(cvv) in (3,4)
                    and self.card_holder.strip() and re.fullmatch(r"(0[1-9]|1[0-2])/\d{2}", self.expiry)):
                raise ValueError("Completa los datos ficticios de tarjeta con formato válido")
        return self


class PaymentResolution(BaseModel):
    result: Literal["approved", "rejected"]


class TransferInput(BaseModel):
    email: EmailStr


class TokenInput(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class ScanInput(TokenInput):
    identity_matches: bool


def own_ticket(connection, ticket_id, user, lock=False):
    query = select(s.tickets, s.wallets.c.user_id.label("owner_user_id"), s.nominations.c.email.label("attendee_email")).join(
        s.wallets, s.wallets.c.id == s.tickets.c.expected_wallet_id).join(s.nominations, and_(s.nominations.c.ticket_id == s.tickets.c.id,
        s.nominations.c.version == s.tickets.c.nomination_version)).where(s.tickets.c.id == ticket_id)
    if lock:
        query = query.with_for_update(of=s.tickets)
    row = connection.execute(query).mappings().one_or_none()
    if not row or (row["owner_user_id"] != user["id"] and row["attendee_email"] != user["email"]):
        raise HTTPException(404, "Boleto no encontrado")
    return row


def ticket_detail(connection, ticket):
    ticket_id = ticket["id"]
    row = connection.execute(select(s.tickets, s.nominations.c.full_name, s.nominations.c.document_type,
        s.nominations.c.document_last_four, s.events.c.name.label("event_name"), s.events.c.starts_at,
        s.events.c.poster_url, s.events.c.status.label("event_status"), s.zones.c.name.label("zone_name"),
        s.inventory_units.c.row_label, s.inventory_units.c.seat_label, s.inventory_units.c.mode,
        s.order_items.c.unit_price, s.order_items.c.currency, s.wallets.c.address.label("owner_address")
    ).join(s.nominations, and_(s.nominations.c.ticket_id == s.tickets.c.id, s.nominations.c.version == s.tickets.c.nomination_version))
      .join(s.events, s.events.c.id == s.tickets.c.event_id).join(s.order_items, s.order_items.c.id == s.tickets.c.order_item_id)
      .join(s.allocations, s.allocations.c.id == s.order_items.c.allocation_id).join(s.inventory_units, s.inventory_units.c.id == s.allocations.c.inventory_unit_id)
      .join(s.zones, s.zones.c.id == s.inventory_units.c.zone_id).join(s.wallets, s.wallets.c.id == s.tickets.c.expected_wallet_id)
      .where(s.tickets.c.id == ticket_id)).mappings().one()
    result = dict(row)
    binding = connection.execute(select(s.nft_bindings).where(s.nft_bindings.c.ticket_id == ticket_id)).mappings().one_or_none()
    result["nft"] = dict(binding) if binding else None
    operations = connection.execute(select(s.chain_operations.c.kind, s.chain_operations.c.status, s.chain_operations.c.tx_hash,
        s.chain_operations.c.block_number, s.chain_operations.c.failure_code).where(s.chain_operations.c.ticket_id == ticket_id)
        .order_by(s.chain_operations.c.created_at)).mappings().all()
    result["operations"] = list(operations)
    return result


def queue_operation(connection, request, ticket_id, kind):
    op_id = uuid4()
    settings = request.app.state.settings
    connection.execute(s.chain_operations.insert().values(id=op_id, ticket_id=ticket_id, kind=kind,
        idempotency_key=op_id, chain_id=settings.chain_id,
        contract_address=(settings.contract_address or "0x" + "0"*40).lower()))
    return op_id


def expire_reservations(connection):
    rows = connection.execute(select(s.reservations.c.id).where(s.reservations.c.status == "active", s.reservations.c.expires_at < func.now())
                              .with_for_update(skip_locked=True)).scalars().all()
    for reservation_id in rows:
        connection.execute(update(s.allocations).where(s.allocations.c.reservation_id == reservation_id, s.allocations.c.status == "held").values(status="released"))
        connection.execute(update(s.reservations).where(s.reservations.c.id == reservation_id).values(status="expired"))
        orders = connection.execute(select(s.orders.c.id).where(s.orders.c.reservation_id == reservation_id, s.orders.c.status == "pending_payment")).scalars().all()
        for order_id in orders:
            connection.execute(update(s.orders).where(s.orders.c.id == order_id).values(status="cancelled"))
            connection.execute(update(s.payments).where(s.payments.c.order_id == order_id, s.payments.c.status == "pending").values(status="rejected"))
            item_ids = select(s.order_items.c.id).where(s.order_items.c.order_id == order_id)
            connection.execute(update(s.tickets).where(s.tickets.c.order_item_id.in_(item_ids)).values(status="cancelled"))


@router.post("/reservations", status_code=201)
def reserve(body: ReserveInput, request: Request, user=Depends(verified_user), connection=Depends(db)):
    limited(request, "reserve", 60)
    expire_reservations(connection)
    event = connection.execute(select(s.events).where(s.events.c.id == body.event_id).with_for_update()).mappings().one_or_none()
    if not event or event["status"] != "published" or not event["sales_open_at"] <= now() < event["sales_close_at"]:
        raise HTTPException(409, "La venta no está disponible")
    zone = connection.execute(select(s.zones).where(s.zones.c.id == body.zone_id, s.zones.c.event_id == body.event_id)).mappings().one_or_none()
    if not zone:
        raise HTTPException(404, "Zona no encontrada")
    live = exists(select(s.allocations.c.id).where(s.allocations.c.inventory_unit_id == s.inventory_units.c.id,
                    s.allocations.c.status.in_(["held", "committed"])))
    query = select(s.inventory_units).where(s.inventory_units.c.zone_id == body.zone_id, s.inventory_units.c.enabled, ~live)
    if zone["mode"] == "seated":
        if not body.unit_ids or len(set(body.unit_ids)) != len(body.unit_ids):
            raise HTTPException(422, "Selecciona hasta seis asientos distintos")
        count = len(body.unit_ids)
        query = query.where(s.inventory_units.c.id.in_(body.unit_ids))
    else:
        if body.unit_ids:
            raise HTTPException(422, "La entrada general se selecciona por cantidad")
        count = body.quantity
    units = connection.execute(query.order_by(s.inventory_units.c.id).limit(count).with_for_update(skip_locked=True)).mappings().all()
    if len(units) != count:
        raise HTTPException(409, "Uno de los lugares ya no está disponible. Actualiza el mapa.")
    reservation = connection.execute(s.reservations.insert().values(buyer_id=user["id"], event_id=body.event_id,
        expires_at=now()+timedelta(minutes=10)).returning(s.reservations)).mappings().one()
    connection.execute(s.allocations.insert(), [dict(reservation_id=reservation["id"], event_id=body.event_id, inventory_unit_id=u["id"]) for u in units])
    return {**dict(reservation), "units": [dict(u) for u in units], "zone": dict(zone), "total": zone["price"]*count}


@router.delete("/reservations/{reservation_id}")
def release(reservation_id: UUID, user=Depends(current_user), connection=Depends(db)):
    row = connection.execute(select(s.reservations).where(s.reservations.c.id == reservation_id, s.reservations.c.buyer_id == user["id"]).with_for_update()).mappings().one_or_none()
    if not row:
        raise HTTPException(404, "Reserva no encontrada")
    if row["status"] != "active":
        raise HTTPException(409, "La reserva ya está cerrada")
    connection.execute(update(s.allocations).where(s.allocations.c.reservation_id == reservation_id, s.allocations.c.status == "held").values(status="released"))
    connection.execute(update(s.reservations).where(s.reservations.c.id == reservation_id).values(status="cancelled"))
    return {"message": "Reserva liberada"}


def resolve_order(connection, request, order, result):
    reservation = connection.execute(select(s.reservations).where(s.reservations.c.id == order["reservation_id"]).with_for_update()).mappings().one()
    if reservation["status"] != "active" or reservation["expires_at"] <= now():
        raise HTTPException(409, "La reserva ya venció")
    approved = result == "approved"
    connection.execute(update(s.orders).where(s.orders.c.id == order["id"]).values(status="paid" if approved else "cancelled"))
    connection.execute(update(s.payments).where(s.payments.c.order_id == order["id"], s.payments.c.status == "pending").values(status=result))
    connection.execute(update(s.reservations).where(s.reservations.c.id == reservation["id"]).values(status="committed" if approved else "cancelled"))
    connection.execute(update(s.allocations).where(s.allocations.c.reservation_id == reservation["id"]).values(status="committed" if approved else "released"))
    tickets = connection.execute(select(s.tickets).join(s.order_items, s.order_items.c.id == s.tickets.c.order_item_id).where(s.order_items.c.order_id == order["id"])).mappings().all()
    for ticket in tickets:
        if approved:
            queue_operation(connection, request, ticket["id"], "mint")
        else:
            connection.execute(update(s.tickets).where(s.tickets.c.id == ticket["id"]).values(status="cancelled"))
    buyer = connection.execute(select(s.users.c.email).where(s.users.c.id == order["buyer_id"])).scalar_one()
    queue_mail(connection, request, buyer, "Compra simulada " + ("aprobada" if approved else "rechazada"),
        "NexoPass\nOrden " + str(order["id"]) + "\nTotal: " + str(order["total"]) + " " + order["currency"] +
        ("\nEl pago fue simulado. Tus NFT se están emitiendo; recibirás cada boleto al confirmarse." if approved else "\nNo se emitieron boletos. Los lugares se liberaron."))


@router.post("/reservations/{reservation_id}/checkout")
def checkout(reservation_id: UUID, body: CheckoutInput, request: Request, user=Depends(verified_user), connection=Depends(db)):
    limited(request, "checkout", 60)
    reservation = connection.execute(select(s.reservations).where(s.reservations.c.id == reservation_id,
        s.reservations.c.buyer_id == user["id"]).with_for_update()).mappings().one_or_none()
    if not reservation:
        raise HTTPException(404, "Reserva no encontrada")
    fingerprint = sha256(json.dumps({"reservation": str(reservation_id), "method": body.method,
        "attendees": [{**a.model_dump(mode="json", exclude={"document_number"}), "document_number": a.document_number.get_secret_value()} for a in body.attendees]}, sort_keys=True).encode()).digest()
    existing = connection.execute(select(s.orders).where(s.orders.c.buyer_id == user["id"], s.orders.c.idempotency_key == body.idempotency_key)).mappings().one_or_none()
    if existing:
        if existing["checkout_fingerprint"] != fingerprint:
            raise HTTPException(409, "La clave de operación ya se utilizó con otros datos")
        return {"order_id": existing["id"], "status": existing["status"]}
    if reservation["status"] != "active" or reservation["expires_at"] <= now():
        raise HTTPException(409, "La reserva ya no está vigente")
    event = connection.execute(select(s.events).where(s.events.c.id == reservation["event_id"])).mappings().one()
    if event["status"] != "published" or not event["sales_open_at"] <= now() < event["sales_close_at"]:
        raise HTTPException(409, "La venta está cerrada")
    units = connection.execute(select(s.allocations.c.id.label("allocation_id"), s.zones.c.price, s.zones.c.currency)
        .join(s.inventory_units, s.inventory_units.c.id == s.allocations.c.inventory_unit_id).join(s.zones, s.zones.c.id == s.inventory_units.c.zone_id)
        .where(s.allocations.c.reservation_id == reservation_id, s.allocations.c.status == "held").order_by(s.inventory_units.c.unit_number)).mappings().all()
    if len(units) != len(body.attendees) or not units:
        raise HTTPException(422, "Debes indicar un asistente por boleto")
    wallet_id = connection.execute(select(s.wallets.c.id).where(s.wallets.c.user_id == user["id"], s.wallets.c.revoked_at.is_(None))).scalar_one()
    order = connection.execute(s.orders.insert().values(reservation_id=reservation_id, event_id=reservation["event_id"], buyer_id=user["id"],
        idempotency_key=body.idempotency_key, checkout_fingerprint=fingerprint, total=sum(u["price"] for u in units), currency=units[0]["currency"]).returning(s.orders)).mappings().one()
    for unit, attendee in zip(units, body.attendees):
        item = connection.execute(s.order_items.insert().values(order_id=order["id"], event_id=reservation["event_id"], reservation_id=reservation_id,
            allocation_id=unit["allocation_id"], currency=unit["currency"], unit_price=unit["price"]).returning(s.order_items.c.id)).scalar_one()
        ticket_id = uuid4()
        connection.execute(s.tickets.insert().values(id=ticket_id, order_item_id=item, event_id=reservation["event_id"], expected_wallet_id=wallet_id))
        document = attendee.document_number.get_secret_value()
        connection.execute(s.nominations.insert().values(ticket_id=ticket_id, version=1, full_name=attendee.full_name.strip(), email=str(attendee.email).lower(),
            document_type=attendee.document_type, document_ciphertext=cipher(request).encrypt(document.encode()), document_last_four=document[-4:], encryption_key_version=1))
    connection.execute(s.payments.insert().values(order_id=order["id"], currency=order["currency"], amount=order["total"], method=body.method, reference=uuid4()))
    if body.result != "pending":
        resolve_order(connection, request, order, body.result)
    audit(connection, user["id"], "order.created", order["id"], "order")
    return {"order_id": order["id"], "status": "paid" if body.result == "approved" else "cancelled" if body.result == "rejected" else "pending_payment"}


@router.post("/orders/{order_id}/resolve-demo")
def resolve_demo(order_id: UUID, body: PaymentResolution, request: Request, user=Depends(verified_user), connection=Depends(db)):
    order = connection.execute(select(s.orders).where(s.orders.c.id == order_id, s.orders.c.buyer_id == user["id"])).mappings().one_or_none()
    if not order:
        raise HTTPException(404, "Orden no encontrada")
    if order["status"] != "pending_payment":
        raise HTTPException(409, "El pago ya está resuelto")
    resolve_order(connection, request, order, body.result)
    return {"message": "Pago de demostración resuelto"}


@router.get("/me/orders")
def my_orders(user=Depends(current_user), connection=Depends(db)):
    return list(connection.execute(select(s.orders.c.id, s.orders.c.event_id, s.orders.c.total, s.orders.c.currency, s.orders.c.status, s.orders.c.created_at).where(s.orders.c.buyer_id == user["id"]).order_by(s.orders.c.created_at.desc()).limit(100)).mappings())


@router.get("/me/tickets")
def my_tickets(user=Depends(current_user), connection=Depends(db)):
    tickets = connection.execute(select(s.tickets).join(s.wallets, s.wallets.c.id == s.tickets.c.expected_wallet_id).join(s.nominations,
        and_(s.nominations.c.ticket_id == s.tickets.c.id, s.nominations.c.version == s.tickets.c.nomination_version))
        .where((s.wallets.c.user_id == user["id"]) | (s.nominations.c.email == user["email"])).order_by(s.tickets.c.created_at.desc()).limit(100)).mappings().all()
    return [ticket_detail(connection, ticket) for ticket in tickets]


@router.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: UUID, user=Depends(current_user), connection=Depends(db)):
    return ticket_detail(connection, own_ticket(connection, ticket_id, user))


def qr_for(connection, request, ticket):
    if ticket["status"] != "active" or ticket["suspended"]:
        raise HTTPException(409, "El boleto no está activo o está pendiente de confirmación")
    event = connection.execute(select(s.events).where(s.events.c.id == ticket["event_id"])).mappings().one()
    if event["status"] != "published" or event["ends_at"] < now():
        raise HTTPException(409, "El concierto no permite ingreso")
    if connection.execute(select(s.chain_operations.c.id).where(s.chain_operations.c.ticket_id == ticket["id"], s.chain_operations.c.status.in_(["queued", "submitted"]))).first():
        raise HTTPException(409, "El boleto tiene una operación pendiente")
    token = secrets.token_urlsafe(32)
    connection.execute(update(s.credentials).where(s.credentials.c.ticket_id == ticket["id"], s.credentials.c.purpose == "entry_qr", s.credentials.c.revoked_at.is_(None)).values(revoked_at=now()))
    expires = now()+timedelta(seconds=60)
    connection.execute(s.credentials.insert().values(token_hash=digest(token), purpose="entry_qr", ticket_id=ticket["id"],
        credential_version=ticket["credential_version"], expires_at=expires))
    output=BytesIO(); qrcode.make(token).save(output, format="PNG")
    return {"image": "data:image/png;base64,"+base64.b64encode(output.getvalue()).decode(), "token": token, "expires_at": expires}


@router.post("/tickets/{ticket_id}/qr")
def ticket_qr(ticket_id: UUID, request: Request, user=Depends(verified_user), connection=Depends(db)):
    return qr_for(connection, request, own_ticket(connection, ticket_id, user, lock=True))


def guest_ticket(connection, token):
    credential = connection.execute(select(s.credentials).where(s.credentials.c.token_hash == digest(token), s.credentials.c.purpose == "ticket_view",
        s.credentials.c.expires_at > func.now(), s.credentials.c.revoked_at.is_(None))).mappings().one_or_none()
    if not credential:
        raise HTTPException(404, "Enlace vencido o inválido")
    ticket = connection.execute(select(s.tickets).where(s.tickets.c.id == credential["ticket_id"],
        s.tickets.c.credential_version == credential["credential_version"]).with_for_update()).mappings().one_or_none()
    if not ticket:
        raise HTTPException(404, "El boleto cambió de titular")
    return ticket


@router.post("/guest/ticket")
def guest_view(body: TokenInput, request: Request, connection=Depends(db)):
    limited(request, "guest", 60)
    return ticket_detail(connection, guest_ticket(connection, body.token))


@router.post("/guest/qr")
def guest_qr(body: TokenInput, request: Request, connection=Depends(db)):
    limited(request, "guest-qr", 120)
    return qr_for(connection, request, guest_ticket(connection, body.token))
