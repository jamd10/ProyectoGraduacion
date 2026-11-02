from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from nexopass.app import create_app
from nexopass.config import Settings


def test_development_exposes_api_schema():
    with TestClient(create_app(Settings(environment="development"))) as client:
        response = client.get("/openapi.json")
        assert response.status_code == 200
        assert response.json()["info"]["title"] == "NexoPass API"
        assert client.get("/docs").status_code == 200


def test_production_does_not_expose_development_docs():
    with TestClient(create_app(Settings(environment="production"))) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404


def test_settings_read_only_prefixed_environment(monkeypatch):
    monkeypatch.setenv("NEXOPASS_ENVIRONMENT", "test")
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert Settings().environment == "test"


def test_invalid_environment_fails_configuration(monkeypatch):
    monkeypatch.setenv("NEXOPASS_ENVIRONMENT", "invalid")
    with pytest.raises(ValidationError):
        Settings()
