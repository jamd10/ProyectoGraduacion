from pydantic import SecretStr, ValidationError
import pytest
from fastapi.testclient import TestClient

from nexopass.app import create_app
from nexopass.config import Settings
from nexopass.database import create_database_engine


def test_missing_password_does_not_fall_back_to_postgres():
    assert create_database_engine(Settings(database_password=None)) is None


def test_admin_or_migrator_cannot_be_runtime_user():
    for user in ("postgres", "nexopass_migrator"):
        with pytest.raises(ValidationError):
            Settings(database_user=user)


def test_password_is_redacted_and_url_preserves_special_characters():
    secret = "test-secret@:/?#%"
    settings = Settings(database_password=SecretStr(secret))
    engine = create_database_engine(settings)
    try:
        assert engine.url.password == secret
        assert secret not in repr(settings)
        assert secret not in settings.model_dump_json()
        assert secret not in repr(engine)
        assert engine.hide_parameters
    finally:
        engine.dispose()


def test_lifespan_disposes_engine(monkeypatch):
    class FakeEngine:
        disposed = False
        def dispose(self):
            self.disposed = True
    engine = FakeEngine()
    monkeypatch.setattr("nexopass.app.create_database_engine", lambda settings: engine)
    app = create_app(Settings())
    with TestClient(app):
        assert app.state.database is engine
        assert not engine.disposed
    assert engine.disposed and app.state.database is None
