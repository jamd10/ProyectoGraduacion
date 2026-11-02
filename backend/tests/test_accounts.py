import os
import re
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import SecretStr
import pytest

from nexopass.app import create_app
from nexopass.config import Settings
from test_integrity import engine


@pytest.fixture
def api(engine, tmp_path):
    settings = Settings(environment="test", database_host=engine.url.host,
        database_port=engine.url.port or 5432, database_name=engine.url.database,
        database_password=SecretStr(os.environ["NEXOPASS_TEST_RUNTIME_PASSWORD"]),
        data_directory=tmp_path, worker_enabled=False,
        chain_rpc_url=os.environ.get("NEXOPASS_TEST_CHAIN_RPC_URL", "http://127.0.0.1:8545"))
    with TestClient(create_app(settings), client=("test-" + uuid4().hex, 50000)) as client:
        yield client


def account(api):
    email = uuid4().hex + "@example.com"
    password = "Graduacion2026!"
    assert api.post("/api/v1/auth/register", json={"email": email, "full_name": "Persona de prueba", "password": password}).status_code == 202
    response = api.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    api.headers["X-CSRF-Token"] = api.cookies.get("nexopass_csrf")
    return email, password


def test_register_verify_profile_and_logout(api):
    account(api)
    assert not api.get("/api/v1/auth/me").json()["verified"]
    messages = api.get("/api/v1/me/mailbox").json()
    token = re.search(r"token=([\w-]+)", messages[0]["body"]).group(1)
    assert api.post("/api/v1/auth/verify", json={"token": token}).status_code == 200
    assert api.post("/api/v1/auth/verify", json={"token": token}).status_code == 400
    assert api.get("/api/v1/auth/me").json()["verified"]
    assert api.patch("/api/v1/auth/me", json={"full_name": "Nombre actualizado"}).status_code == 200
    assert api.get("/api/v1/auth/me").json()["full_name"] == "Nombre actualizado"
    assert api.post("/api/v1/auth/logout").status_code == 200
    assert api.get("/api/v1/auth/me").status_code == 401


def test_csrf_and_cross_origin_rejected(api):
    account(api)
    token = api.headers.pop("X-CSRF-Token")
    assert api.patch("/api/v1/auth/me", json={"full_name": "Intruso"}).status_code == 403
    api.headers["X-CSRF-Token"] = token
    assert api.patch("/api/v1/auth/me", headers={"Origin": "https://attacker.example"}, json={"full_name": "Intruso"}).status_code == 403


def test_password_reset_revokes_sessions_and_token(api):
    email, password = account(api)
    assert api.post("/api/v1/auth/forgot", json={"email": email}).status_code == 202
    message = next(m for m in api.get("/api/v1/me/mailbox").json() if "Recupera" in m["subject"])
    token = re.search(r"token=([\w-]+)", message["body"]).group(1)
    body = {"token": token, "password": "NuevaGraduacion2026!"}
    assert api.post("/api/v1/auth/reset", json=body).status_code == 200
    assert api.get("/api/v1/auth/me").status_code == 401
    assert api.post("/api/v1/auth/reset", json=body).status_code == 400
    assert api.post("/api/v1/auth/login", json={"email": email, "password": password}).status_code == 401


def test_validation_never_echoes_password(api):
    value = "secret-invalid"
    response = api.post("/api/v1/auth/register", json={"email": "invalid", "full_name": "Test", "password": value})
    assert response.status_code == 422 and value not in response.text
