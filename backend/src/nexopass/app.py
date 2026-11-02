"""Factory de FastAPI. Importar este módulo no abre conexiones ni crea tablas."""
from fastapi import FastAPI

from nexopass.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings()
    app = FastAPI(
        title="NexoPass API", version="0.1.0", debug=False,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )
    app.state.settings = settings
    return app
