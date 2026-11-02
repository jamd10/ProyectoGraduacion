from datetime import timedelta
import secrets
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, update, func, and_
from sqlalchemy.dialects.postgresql import insert

from nexopass import schema as s
from nexopass.security import db, current_user, verified_user, cipher, digest, now, audit, limited
from nexopass.commerce import TransferInput, TokenInput, Attendee, own_ticket, queue_operation
from nexopass.mail import queue_mail

router = APIRouter(prefix="/api/v1", tags=["Transfers"])


@router.post("/tickets/{ticket_id}/transfers", status_code=201)
def invite(ticket_id: UUID, body: TransferInput, request: Request, user=Depends(verified_user), connection=Depends(db)):
    limited(request, "transfer", 20)
    ticket = own_ticket(connection, ticket_id, user, lock=True)
    if ticket["owner_user_id"] != user["id"]:
        raise HTTPException(403, "La solicitud debe autorizarla el propietario del NFT")
    event = connection.execute(select(s.events).where(s.events.c.id == ticket["event_id"])).mappings().one()
    if ticket["status"] != "active" or ticket["suspended"] or ticket["transfer_count"] or event["status"] != "published" or event["transfer_deadline"] <= now():
        raise HTTPException(409, "Este boleto ya no admite transferencias")
    if connection.execute(select(s.chain_operations.c.id).where(s.chain_operations.c.ticket_id == ticket_id,
        s.chain_operations.c.status.in_(["queued", "submitted"]))).first():
        raise HTTPException(409, "El boleto tiene una operación en curso")
    email = str(body.email).lower()
    if email == ticket["attendee_email"]:
        raise HTTPException(422, "La transferencia requiere un asistente diferente")
    transfer_id = uuid4()
    expires = min(now()+timedelta(hours=24), event["transfer_deadline"])
    holder_authorized = user["email"] == ticket["attendee_email"]
    connection.execute(s.transfers.insert().values(id=transfer_id, ticket_id=ticket_id, requested_by=user["id"],
        from_nomination_version=ticket["nomination_version"], recipient_email=email, expires_at=expires,
        owner_authorized_at=now(), holder_authorized_at=now() if holder_authorized else None))
    if not holder_authorized:
        token = secrets.token_urlsafe(32)
        connection.execute(s.credentials.insert().values(token_hash=digest(token), purpose="transfer_authorize",
            ticket_id=ticket_id, transfer_id=transfer_id, expires_at=expires))
        queue_mail(connection, request, ticket["attendee_email"], "Autoriza el cambio de tu boleto",
            "El comprador solicitó transferir tu boleto de " + event["name"] + ".\nAutoriza solo si estás de acuerdo:\n" +
            request.app.state.settings.public_url + "/authorize-transfer?token=" + token)
    queue_mail(connection, request, email, "Invitación para recibir un boleto",
        "Tienes una invitación de NexoPass. Regístrate o inicia sesión con este correo y revisa Transferencias:\n" + request.app.state.settings.public_url + "/transfers")
    audit(connection, user["id"], "transfer.invited", ticket_id)
    return {"id": transfer_id, "holder_authorized": holder_authorized, "expires_at": expires}


@router.post("/transfers/authorize")
def authorize(body: TokenInput, request: Request, connection=Depends(db)):
    limited(request, "authorize-transfer", 30)
    credential = connection.execute(select(s.credentials).where(s.credentials.c.token_hash == digest(body.token),
        s.credentials.c.purpose == "transfer_authorize", s.credentials.c.expires_at > func.now(), s.credentials.c.revoked_at.is_(None),
        s.credentials.c.consumed_at.is_(None)).with_for_update()).mappings().one_or_none()
    if not credential:
        raise HTTPException(400, "Enlace inválido o utilizado")
    transfer = connection.execute(select(s.transfers).where(s.transfers.c.id == credential["transfer_id"],
        s.transfers.c.status == "invited", s.transfers.c.expires_at > func.now()).with_for_update()).mappings().one_or_none()
    if not transfer:
        raise HTTPException(409, "La invitación ya no está vigente")
    connection.execute(update(s.credentials).where(s.credentials.c.id == credential["id"]).values(consumed_at=now()))
    connection.execute(update(s.transfers).where(s.transfers.c.id == transfer["id"]).values(holder_authorized_at=now()))
    audit(connection, None, "transfer.holder_authorized", transfer["ticket_id"])
    return {"message": "Autorización registrada; el receptor debe aceptar con su cuenta"}


@router.get("/me/transfers")
def my_transfers(user=Depends(current_user), connection=Depends(db)):
    return list(connection.execute(select(s.transfers, s.events.c.name.label("event_name"))
        .join(s.tickets, s.tickets.c.id == s.transfers.c.ticket_id).join(s.events, s.events.c.id == s.tickets.c.event_id)
        .where((s.transfers.c.recipient_email == user["email"]) | (s.transfers.c.requested_by == user["id"]))
        .order_by(s.transfers.c.created_at.desc()).limit(100)).mappings())


@router.post("/transfers/{transfer_id}/accept")
def accept(transfer_id: UUID, body: Attendee, request: Request, user=Depends(verified_user), connection=Depends(db)):
    # Bloqueo de boleto antes de modificar una operación, igual que ingreso e invitación.
    reference = connection.execute(select(s.transfers.c.ticket_id).where(s.transfers.c.id == transfer_id,
        s.transfers.c.recipient_email == user["email"])).scalar_one_or_none()
    if not reference:
        raise HTTPException(404, "Transferencia no encontrada")
    ticket = connection.execute(select(s.tickets).where(s.tickets.c.id == reference).with_for_update()).mappings().one()
    transfer = connection.execute(select(s.transfers).where(s.transfers.c.id == transfer_id).with_for_update()).mappings().one()
    event = connection.execute(select(s.events).where(s.events.c.id == ticket["event_id"])).mappings().one()
    if transfer["status"] != "invited" or transfer["expires_at"] <= now() or event["transfer_deadline"] <= now() or event["status"] != "published":
        raise HTTPException(409, "La invitación ya no está disponible")
    if not transfer["holder_authorized_at"]:
        raise HTTPException(409, "El asistente actual debe autorizar primero el cambio por correo")
    if ticket["status"] != "active" or ticket["suspended"] or ticket["transfer_count"] or ticket["nomination_version"] != transfer["from_nomination_version"]:
        raise HTTPException(409, "El boleto ya no admite este cambio")
    if str(body.email).lower() != user["email"]:
        raise HTTPException(422, "El asistente debe coincidir con la cuenta receptora")
    wallet = connection.execute(select(s.wallets.c.id).where(s.wallets.c.user_id == user["id"], s.wallets.c.revoked_at.is_(None))).scalar_one()
    document = body.document_number.get_secret_value()
    values = dict(ticket_id=ticket["id"], version=ticket["nomination_version"]+1, user_id=user["id"], full_name=body.full_name.strip(),
        email=user["email"], document_type=body.document_type, document_ciphertext=cipher(request).encrypt(document.encode()),
        document_last_four=document[-4:], encryption_key_version=1)
    connection.execute(insert(s.nominations).values(**values).on_conflict_do_update(index_elements=["ticket_id", "version"],
        set_={k:v for k,v in values.items() if k not in ("ticket_id", "version")}))
    connection.execute(update(s.transfers).where(s.transfers.c.id == transfer_id).values(status="accepted", recipient_user_id=user["id"],
        target_wallet_id=wallet, recipient_accepted_at=now()))
    queue_operation(connection, request, ticket["id"], "transfer")
    audit(connection, user["id"], "transfer.accepted", ticket["id"])
    return {"message": "Transferencia enviada a blockchain; aún no está confirmada"}


@router.post("/transfers/{transfer_id}/cancel")
def cancel(transfer_id: UUID, user=Depends(current_user), connection=Depends(db)):
    transfer = connection.execute(select(s.transfers).where(s.transfers.c.id == transfer_id,
        s.transfers.c.requested_by == user["id"]).with_for_update()).mappings().one_or_none()
    if not transfer:
        raise HTTPException(404, "Transferencia no encontrada")
    if transfer["status"] != "invited":
        raise HTTPException(409, "La transferencia ya no puede cancelarse")
    connection.execute(update(s.transfers).where(s.transfers.c.id == transfer_id).values(status="cancelled"))
    connection.execute(update(s.credentials).where(s.credentials.c.transfer_id == transfer_id).values(revoked_at=now()))
    return {"message": "Invitación cancelada"}
