from fastapi.testclient import TestClient
from nexopass.app import create_app
from nexopass.config import Settings


def test_spa_routes_do_not_hide_unknown_api_or_disabled_docs(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>NexoPass</title>")
    settings = Settings(environment="production", frontend_directory=dist, data_directory=tmp_path, database_password=None)
    with TestClient(create_app(settings)) as client:
        assert client.get('/').status_code == 200
        assert client.get('/tickets').status_code == 200
        assert client.get('/api/v1/nonexistent').status_code == 404
        assert client.get('/docs').status_code == 404
        assert client.get('/missing.js').status_code == 404
        assert 'frame-ancestors' in client.get('/').headers['content-security-policy']
