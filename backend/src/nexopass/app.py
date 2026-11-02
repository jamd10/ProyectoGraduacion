"""Factory de FastAPI. Importar este módulo no abre conexiones ni crea tablas."""
from contextlib import asynccontextmanager
from fastapi import FastAPI

from nexopass.config import Settings
from nexopass.database import create_database_engine
from nexopass.health import router as health_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings()
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = create_database_engine(settings)
        app.state.database = engine
        try:
            yield
        finally:
            if engine is not None:
                engine.dispose()
            app.state.database = None

    app = FastAPI(
        title="NexoPass API", version="0.1.0", debug=False, lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )
    app.include_router(health_router)
    app.state.settings = settings
    return app
