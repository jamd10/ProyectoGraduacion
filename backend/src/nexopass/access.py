from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, and_, update, func

from nexopass import schema as s
from nexopass.security import db, current_user, cipher, digest, now, roles_for, audit, limited
from nexopass.commerce import TokenInput, ScanInput, queue_operation

router = APIRouter(prefix="/api/v1/access", tags=["Admission"])


@router.get("/events")
def staff_events(user=Depends(current_user), connection=Depends(db)):
    query = select(s.events.c.id, s.events.c.name, s.events.c.starts_at, s.events.c.status)
    if "admin" not in roles_for(connection, user["id"]):
        query = query.join(s.event_staff, s.event_staff.c.event_id == s.events.c.id).where(s.event_staff.c.user_id == user["id"], s.event_staff.c.disabled_at.is_(None))
    return list(connection.execute(query.order_by(s.events.c.starts_at)).mappings())


def authorize_staff(connection, user, event_id):
    assigned = connection.execute(select(s.event_staff.c.user_id).where(s.event_staff.c.user_id == user["id"], s.event_staff.c.event_id == event_id, s.event_staff.c.disabled_at.is_(None))).first()
    if not assigned and "admin" not in roles_for(connection, user["id"]):
        raise HTTPException(403, "No estás asignado a este concierto")
    if not assigned:
        from sqlalchemy.dialects.postgresql import insert
        connection.execute(insert(s.event_staff).values(event_id=event_id, user_id=user["id"]).on_conflict_do_update(index_elements=["event_id", "user_id"], set_={"disabled_at": None}))


def lookup(connection, request, token, user):
    credential = connection.execute(select(s.credentials).where(s.credentials.c.token_hash == digest(token),
        s.credentials.c.purpose == "entry_qr", s.credentials.c.expires_at > func.now(), s.credentials.c.revoked_at.is_(None),
        s.credentials.c.consumed_at.is_(None))).mappings().one_or_none()
    if not credential:
        raise HTTPException(400, "QR inválido, vencido o ya utilizado")
    ticket = connection.execute(select(s.tickets).where(s.tickets.c.id == credential["ticket_id"]).with_for_update()).mappings().one()
    credential = connection.execute(select(s.credentials).where(s.credentials.c.id == credential["id"],
        s.credentials.c.expires_at > func.now(), s.credentials.c.revoked_at.is_(None), s.credentials.c.consumed_at.is_(None)).with_for_update()).mappings().one_or_none()
    if not credential:
        raise HTTPException(400, "QR renovado, vencido o utilizado")
    authorize_staff(connection, user, ticket["event_id"])
    event = connection.execute(select(s.events).where(s.events.c.id == ticket["event_id"])).mappings().one()
    if ticket["status"] != "active" or ticket["suspended"] or ticket["credential_version"] != credential["credential_version"] or event["status"] != "published":
        raise HTTPException(409, "Boleto inactivo, usado o con titular cambiado")
    nomination = connection.execute(select(s.nominations).where(s.nominations.c.ticket_id == ticket["id"], s.nominations.c.version == ticket["nomination_version"])).mappings().one()
    return ticket, event, nomination, credential


@router.post("/check")
def check(body: TokenInput, request: Request, user=Depends(current_user), connection=Depends(db)):
    limited(request, "access-check", 300)
    ticket, event, nomination, credential = lookup(connection, request, body.token, user)
    return {"ticket_id": ticket["id"], "event": event["name"], "full_name": nomination["full_name"],
        "document_type": nomination["document_type"], "document_number": cipher(request).decrypt(nomination["document_ciphertext"]).decode(),
        "within_window": event["doors_open_at"] <= now() <= event["ends_at"], "message": "Compara el documento antes de confirmar. Esta consulta no autoriza entrada."}


@router.post("/consume")
def consume(body: ScanInput, request: Request, user=Depends(current_user), connection=Depends(db)):
    ticket, event, nomination, credential = lookup(connection, request, body.token, user)
    existing = connection.execute(select(s.admission_attempts).where(s.admission_attempts.c.ticket_id == ticket["id"],
        s.admission_attempts.c.status.in_(["pending", "confirmed"]))).mappings().one_or_none()
    if existing:
        return {"attempt_id": existing["id"], "status": existing["status"]}
    if not body.identity_matches:
        attempt = connection.execute(s.admission_attempts.insert().values(ticket_id=ticket["id"], event_id=event["id"], staff_id=user["id"],
            credential_version=ticket["credential_version"], nomination_version=ticket["nomination_version"], identity_matched=False,
            status="denied", reason_code="identity_mismatch").returning(s.admission_attempts.c.id)).scalar_one()
        audit(connection, user["id"], "admission.identity_mismatch", ticket["id"])
        return {"attempt_id": attempt, "status": "denied"}
    if not event["doors_open_at"] <= now() <= event["ends_at"]:
        raise HTTPException(409, "Fuera del horario de ingreso")
    op = queue_operation(connection, request, ticket["id"], "consume")
    attempt = connection.execute(s.admission_attempts.insert().values(ticket_id=ticket["id"], event_id=event["id"], staff_id=user["id"],
        credential_version=ticket["credential_version"], nomination_version=ticket["nomination_version"], identity_matched=True,
        chain_operation_id=op, status="pending").returning(s.admission_attempts.c.id)).scalar_one()
    return {"attempt_id": attempt, "status": "pending", "message": "Espera confirmación; todavía no autorices entrada"}


@router.get("/attempts/{attempt_id}")
def attempt(attempt_id: UUID, user=Depends(current_user), connection=Depends(db)):
    row = connection.execute(select(s.admission_attempts).where(s.admission_attempts.c.id == attempt_id)).mappings().one_or_none()
    if not row:
        raise HTTPException(404, "Validación no encontrada")
    authorize_staff(connection, user, row["event_id"])
    event_status = connection.execute(select(s.events.c.status).where(s.events.c.id == row["event_id"])).scalar_one()
    ticket = connection.execute(select(s.tickets.c.status, s.tickets.c.suspended).where(s.tickets.c.id == row["ticket_id"])).one()
    authorized = row["status"] == "confirmed" and event_status == "published" and ticket.status == "used" and not ticket.suspended
    return {"id": row["id"], "status": row["status"], "authorized": authorized}
