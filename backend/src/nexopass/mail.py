"""Mensajes transaccionales cifrados; SMTP opcional y bandeja privada local."""
from datetime import timedelta
from uuid import uuid4

from nexopass import schema as s
from nexopass.security import cipher, digest, now
import secrets


def queue_mail(connection, request, recipient, subject, body):
    if request.app.state.settings.environment == "production" and not request.app.state.settings.smtp_host:
        from fastapi import HTTPException
        raise HTTPException(503, "Falta configurar el envío de correo")
    connection.execute(s.email_messages.insert().values(id=uuid4(), recipient=recipient.lower(),
        subject=subject, encrypted_body=cipher(request).encrypt(body.encode()),
        status="pending" if request.app.state.settings.smtp_host else "local"))


def issue_token(connection, request, user, purpose):
    token = secrets.token_urlsafe(32)
    connection.execute(s.credentials.insert().values(token_hash=digest(token), purpose=purpose,
        user_id=user["id"], expires_at=now() + timedelta(minutes=30)))
    path = "verify" if purpose == "verify_email" else "reset"
    url = request.app.state.settings.public_url.rstrip("/") + "/" + path + "?token=" + token
    queue_mail(connection, request, user["email"], "Verifica tu correo" if path == "verify" else "Recupera tu acceso",
        "NexoPass\n\nAbre este enlace para continuar:\n" + url + "\n\nVence en 30 minutos. Si no lo solicitaste, ignóralo.")
