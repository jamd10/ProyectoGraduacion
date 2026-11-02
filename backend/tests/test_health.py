import os

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.exc import OperationalError

from nexopass.app import create_app
from nexopass.config import Settings
from nexopass.health import REQUIRED_SCHEMA_REVISION
from test_integrity import engine


def test_live_does_not_require_database():
    with TestClient(create_app(Settings(database_password=None))) as client:
        response = client.get("/api/v1/health/live")
        assert response.status_code == 200 and response.json() == {"status": "ok"}
        assert response.headers["Cache-Control"] == "no-store"
        assert client.get("/api/v1/health/ready").status_code == 503


def test_ready_without_credentials_is_not_ready():
    with TestClient(create_app(Settings(database_password=None))) as client:
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 503 and response.json() == {"status": "not_ready"}
        assert response.headers["Cache-Control"] == "no-store"


def test_database_failure_does_not_leak_to_response_or_logs(caplog):
    secret = "sensitive-example-not-a-real-password"
    class FailingEngine:
        def connect(self):
            raise OperationalError("private SQL", {"password": secret}, RuntimeError(secret))
    with TestClient(create_app(Settings(database_password=None))) as client:
        client.app.state.database = FailingEngine()
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 503
        assert response.json() == {"status": "not_ready"}
        assert client.get("/api/v1/health/live").status_code == 200
    assert secret not in response.text + caplog.text
    assert "private SQL" not in response.text + caplog.text


@pytest.mark.parametrize("row", [None,
    {"runtime_user": "nexopass_app", "version_num": "outdated"},
    {"runtime_user": "postgres", "version_num": REQUIRED_SCHEMA_REVISION},
])
def test_incompatible_revision_or_role_is_not_ready(row):
    class Result:
        def mappings(self): return self
        def one_or_none(self): return row
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, statement): return Result()
    class Engine:
        def connect(self): return Connection()
    with TestClient(create_app(Settings(database_password=None))) as client:
        client.app.state.database = Engine()
        assert client.get("/api/v1/health/ready").status_code == 503


def test_ready_with_real_runtime_role_and_current_migration(engine):
    password = os.environ.get("NEXOPASS_TEST_RUNTIME_PASSWORD")
    if not password:
        pytest.fail("Falta NEXOPASS_TEST_RUNTIME_PASSWORD.")
    settings = Settings(environment="test", database_host=engine.url.host,
        database_port=engine.url.port or 5432, database_name=engine.url.database,
        database_password=SecretStr(password))
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 200 and response.json() == {"status": "ready"}
        assert response.headers["Cache-Control"] == "no-store"

def test_real_unreachable_database_keeps_liveness_available():
    import socket
    # Puerto ligado pero sin servidor PostgreSQL escuchando: rechazo real de conexión.
    with socket.socket() as unavailable:
        unavailable.bind(("127.0.0.1", 0))
        settings = Settings(database_port=unavailable.getsockname()[1],
            database_password=SecretStr("test-only"), database_connect_timeout=1)
        with TestClient(create_app(settings)) as client:
            assert client.get("/api/v1/health/ready").status_code == 503
            assert client.get("/api/v1/health/live").status_code == 200
