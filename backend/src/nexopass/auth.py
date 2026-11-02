from datetime import timedelta
from uuid import UUID, uuid4
import secrets

from argon2.exceptions import VerificationError
from eth_account import Account
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field, SecretStr
from sqlalchemy import select, update, delete, func
from sqlalchemy.dialects.postgresql import insert

from nexopass import schema as s
from nexopass.inputs import InputModel
from nexopass.security import db, current_user, hasher, DUMMY_HASH, cipher, digest, now, roles_for, limited
from nexopass.mail import issue_token

router = APIRouter(prefix="/api/v1", tags=["Accounts"])


class Registration(InputModel):
    full_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    password: SecretStr = Field(min_length=10, max_length=128)


class Login(InputModel):
    email: EmailStr
    password: SecretStr = Field(min_length=1, max_length=128)


class EmailInput(InputModel):
    email: EmailStr


class TokenInput(InputModel):
    token: str = Field(min_length=20, max_length=200)


class ResetInput(TokenInput):
    password: SecretStr = Field(min_length=10, max_length=128)


class ProfileInput(InputModel):
    full_name: str = Field(min_length=2, max_length=200)


def public_user(connection, user):
    return {"id": user["id"], "email": user["email"], "full_name": user["full_name"],
            "avatar_url": user["avatar_url"], "verified": bool(user["email_verified_at"]),
            "roles": roles_for(connection, user["id"])}


@router.post("/auth/register", status_code=202)
def register(body: Registration, request: Request, connection=Depends(db)):
    limited(request, "register", 10)
    email = str(body.email).lower()
    password_hash = hasher.hash(body.password.get_secret_value())
    user_id = connection.execute(insert(s.users).values(email=email, full_name=body.full_name.strip(),
        password_hash=password_hash).on_conflict_do_nothing(index_elements=["email"]).returning(s.users.c.id)).scalar_one_or_none()
    if user_id:
        account = Account.create()
        connection.execute(s.wallets.insert().values(user_id=user_id, address=account.address.lower(), kind="embedded",
            encrypted_private_key=cipher(request).encrypt(bytes(account.key)), verified_at=now()))
        issue_token(connection, request, {"id": user_id, "email": email}, "verify_email")
    return {"message": "Si el correo está disponible, recibirás un enlace de verificación."}


@router.post("/auth/login")
def login(body: Login, request: Request, response: Response, connection=Depends(db)):
    limited(request, "login", 30)
    user = connection.execute(select(s.users).where(s.users.c.email == str(body.email).lower())).mappings().one_or_none()
    try:
        hasher.verify(user["password_hash"] if user else DUMMY_HASH, body.password.get_secret_value())
        valid = bool(user and not user["disabled_at"])
    except VerificationError:
        valid = False
    if not valid:
        raise HTTPException(401, "Correo o contraseña incorrectos")
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    connection.execute(s.sessions.insert().values(user_id=user["id"], token_hash=digest(token),
        csrf_hash=digest(csrf), expires_at=now() + timedelta(hours=8)))
    secure = request.app.state.settings.environment == "production"
    response.set_cookie("nexopass_session", token, httponly=True, secure=secure, samesite="lax", max_age=28800)
    response.set_cookie("nexopass_csrf", csrf, httponly=False, secure=secure, samesite="lax", max_age=28800)
    return public_user(connection, user)


@router.get("/auth/me")
def me(user=Depends(current_user), connection=Depends(db)):
    return public_user(connection, user)


@router.patch("/auth/me")
def profile(body: ProfileInput, user=Depends(current_user), connection=Depends(db)):
    connection.execute(update(s.users).where(s.users.c.id == user["id"]).values(full_name=body.full_name.strip()))
    return {"message": "Perfil actualizado; los boletos emitidos conservan su nominación."}


@router.post("/auth/logout")
def logout(request: Request, response: Response, user=Depends(current_user), connection=Depends(db)):
    connection.execute(delete(s.sessions).where(s.sessions.c.token_hash == digest(request.cookies.get("nexopass_session", ""))))
    response.delete_cookie("nexopass_session")
    response.delete_cookie("nexopass_csrf")
    return {"message": "Sesión cerrada"}


@router.post("/auth/verify")
def verify(body: TokenInput, request: Request, connection=Depends(db)):
    limited(request, "verify", 30)
    token = connection.execute(select(s.credentials).where(s.credentials.c.token_hash == digest(body.token),
        s.credentials.c.purpose == "verify_email", s.credentials.c.expires_at > func.now(),
        s.credentials.c.consumed_at.is_(None), s.credentials.c.revoked_at.is_(None)).with_for_update()).mappings().one_or_none()
    if not token:
        raise HTTPException(400, "El enlace venció o ya fue utilizado")
    connection.execute(update(s.credentials).where(s.credentials.c.id == token["id"]).values(consumed_at=now()))
    connection.execute(update(s.users).where(s.users.c.id == token["user_id"]).values(email_verified_at=now()))
    return {"message": "Correo verificado"}


@router.post("/auth/resend")
def resend(request: Request, user=Depends(current_user), connection=Depends(db)):
    limited(request, "resend", 5)
    if not user["email_verified_at"]:
        issue_token(connection, request, user, "verify_email")
    return {"message": "Revisa tu correo"}


@router.post("/auth/forgot", status_code=202)
def forgot(body: EmailInput, request: Request, connection=Depends(db)):
    limited(request, "forgot", 10)
    user = connection.execute(select(s.users).where(s.users.c.email == str(body.email).lower())).mappings().one_or_none()
    if user:
        issue_token(connection, request, user, "reset_password")
    return {"message": "Si existe la cuenta, recibirá instrucciones."}


@router.post("/auth/reset")
def reset(body: ResetInput, request: Request, connection=Depends(db)):
    limited(request, "reset", 10)
    token = connection.execute(select(s.credentials).where(s.credentials.c.token_hash == digest(body.token),
        s.credentials.c.purpose == "reset_password", s.credentials.c.expires_at > func.now(),
        s.credentials.c.consumed_at.is_(None), s.credentials.c.revoked_at.is_(None))).mappings().one_or_none()
    if not token:
        raise HTTPException(400, "El enlace venció o ya fue utilizado")
    # Serializar resets concurrentes del mismo usuario e invalidar todos sus enlaces.
    connection.execute(select(s.users.c.id).where(s.users.c.id == token["user_id"]).with_for_update())
    token = connection.execute(select(s.credentials).where(s.credentials.c.token_hash == digest(body.token),
        s.credentials.c.purpose == "reset_password", s.credentials.c.expires_at > func.now(),
        s.credentials.c.consumed_at.is_(None), s.credentials.c.revoked_at.is_(None)).with_for_update()).mappings().one_or_none()
    if not token:
        raise HTTPException(400, "El enlace venció o ya fue utilizado")
    connection.execute(update(s.users).where(s.users.c.id == token["user_id"]).values(password_hash=hasher.hash(body.password.get_secret_value())))
    connection.execute(update(s.credentials).where(s.credentials.c.user_id == token["user_id"], s.credentials.c.purpose == "reset_password").values(revoked_at=now()))
    connection.execute(delete(s.sessions).where(s.sessions.c.user_id == token["user_id"]))
    return {"message": "Contraseña actualizada. Inicia sesión de nuevo."}


@router.get("/me/mailbox")
def mailbox(request: Request, user=Depends(current_user), connection=Depends(db)):
    if request.app.state.settings.environment == "production":
        raise HTTPException(404, "No encontrado")
    rows = connection.execute(select(s.email_messages).where(s.email_messages.c.recipient == user["email"]).order_by(s.email_messages.c.created_at.desc()).limit(30)).mappings()
    return [{"id": row["id"], "subject": row["subject"], "body": cipher(request).decrypt(row["encrypted_body"]).decode(),
             "created_at": row["created_at"], "status": row["status"]} for row in rows]
