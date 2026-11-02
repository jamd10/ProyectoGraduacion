"""Sesiones opacas, cifrado autenticado y controles compartidos."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import secrets
from functools import lru_cache
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select, func, or_, update
from sqlalchemy.dialects.postgresql import insert

from nexopass import schema as s

hasher = PasswordHasher()
DUMMY_HASH = hasher.hash("non-user-dummy-password")


def now():
    return datetime.now(timezone.utc)


def digest(value):
    return sha256(value.encode()).digest()


def db(request: Request):
    engine = request.app.state.database
    if engine is None:
        raise HTTPException(503, "Servicio temporalmente no disponible")
    with engine.begin() as connection:
        yield connection


def cipher(request: Request):
    settings = request.app.state.settings
    if settings.encryption_key:
        return Fernet(settings.encryption_key.get_secret_value().encode())
    if settings.environment == "production":
        raise HTTPException(503, "Falta configurar la clave de cifrado")
    return local_cipher(str(settings.data_directory))


@lru_cache(maxsize=8)
def local_cipher(directory):
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    keyfile = path / "master.key"
    try:
        with keyfile.open("xb") as file:
            file.write(Fernet.generate_key())
    except FileExistsError:
        pass
    return Fernet(keyfile.read_bytes())


def limited(request, scope, maximum=10):
    engine = request.app.state.database
    if engine is None:
        raise HTTPException(503, "Servicio temporalmente no disponible")
    # No confiar en X-Forwarded-For de clientes sin un proxy expresamente configurado.
    key = sha256((scope + ":" + (request.client.host if request.client else "unknown")).encode()).hexdigest()
    with engine.begin() as connection:
        query = insert(s.rate_limits).values(key=key, window_start=now(), attempts=1)
        old = s.rate_limits.c.window_start < now() - timedelta(minutes=10)
        from sqlalchemy import case
        query = query.on_conflict_do_update(index_elements=["key"], set_={
            "window_start": case((old, now()), else_=s.rate_limits.c.window_start),
            "attempts": case((old, 1), else_=s.rate_limits.c.attempts + 1),
        }).returning(s.rate_limits.c.attempts)
        attempts = connection.execute(query).scalar_one()
    if attempts > maximum:
        raise HTTPException(429, "Demasiados intentos. Espera unos minutos.")


def current_user(request: Request, connection=Depends(db)):
    token = request.cookies.get("nexopass_session", "")
    row = connection.execute(select(s.users, s.sessions.c.csrf_hash).join(
        s.sessions, s.sessions.c.user_id == s.users.c.id
    ).where(s.sessions.c.token_hash == digest(token), s.sessions.c.expires_at > func.now(),
            s.users.c.disabled_at.is_(None))).mappings().one_or_none()
    if row is None:
        raise HTTPException(401, "Inicia sesión para continuar")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        csrf = request.headers.get("X-CSRF-Token", "")
        if not csrf or not hmac.compare_digest(digest(csrf), row["csrf_hash"]):
            raise HTTPException(403, "Sesión de formulario inválida")
    return dict(row)


def roles_for(connection, user_id):
    roles = list(connection.execute(select(s.user_roles.c.role_code).where(s.user_roles.c.user_id == user_id)).scalars())
    if connection.execute(select(s.event_staff.c.user_id).where(s.event_staff.c.user_id == user_id).limit(1)).first():
        roles.append("staff")
    return sorted(set(roles))


def admin_user(user=Depends(current_user), connection=Depends(db)):
    if "admin" not in roles_for(connection, user["id"]):
        raise HTTPException(403, "Acceso exclusivo de administración")
    return user


def verified_user(user=Depends(current_user)):
    if not user["email_verified_at"]:
        raise HTTPException(403, "Verifica tu correo para continuar")
    return user


def audit(connection, user_id, action, entity_id, entity_type="ticket", details=None):
    from uuid import uuid4
    connection.execute(s.audit_entries.insert().values(actor_user_id=user_id, action=action,
        entity_type=entity_type, entity_id=entity_id, request_id=uuid4(), details=details or {}))
