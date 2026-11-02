"""Factory de FastAPI. Importar este módulo no abre conexiones ni crea tablas."""
from contextlib import asynccontextmanager, suppress
import asyncio
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
import hmac
from starlette.staticfiles import StaticFiles
from nexopass.static import FrontendFiles, UploadBodyLimit

from nexopass.config import Settings
from nexopass.database import create_database_engine
from nexopass.health import router as health_router
from nexopass.auth import router as auth_router
from nexopass.catalog import router as catalog_router
from nexopass.commerce import router as commerce_router
from nexopass.transfers import router as transfers_router
from nexopass.access import router as access_router
from nexopass.worker import run_worker


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings()
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = create_database_engine(settings)
        app.state.database = engine
        task = asyncio.create_task(run_worker(settings, engine)) if engine is not None and settings.worker_enabled and settings.environment != "test" else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
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
    app.include_router(auth_router)
    app.include_router(catalog_router)
    app.include_router(commerce_router)
    app.include_router(transfers_router)
    app.include_router(access_router)
    app.state.settings = settings
    app.add_middleware(UploadBodyLimit)
    @app.middleware("http")
    async def request_safety(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            allowed = {settings.public_url.rstrip("/"), str(request.base_url).rstrip("/")}
            if settings.environment != "production":
                allowed |= {"http://127.0.0.1:5173", "http://localhost:5173"}
            if origin and origin.rstrip("/") not in allowed:
                return JSONResponse({"detail": "Origen no permitido"}, status_code=403)
            if request.cookies.get("nexopass_session"):
                token = request.headers.get("X-CSRF-Token", "")
                cookie = request.cookies.get("nexopass_csrf", "")
                if not token or not cookie or not hmac.compare_digest(token, cookie):
                    return JSONResponse({"detail": "Sesión de formulario inválida"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if not request.url.path.startswith(("/docs", "/openapi.json")):
            response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; script-src 'self'; connect-src 'self'; media-src 'self' blob:; worker-src 'self' blob:; frame-ancestors 'none'"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return JSONResponse({"detail": [{"loc": item["loc"], "msg": item["msg"], "type": item["type"]}
                                      for item in error.errors()]}, status_code=422)

    @app.exception_handler(IntegrityError)
    async def integrity_error(request, error):
        return JSONResponse({"detail": "La operación entra en conflicto con un registro existente"}, status_code=409)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, error):
        return JSONResponse({"detail": "Servicio temporalmente no disponible"}, status_code=503)

    uploads = settings.data_directory / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=uploads), name="media")
    if settings.frontend_directory.is_dir():
        app.mount("/", FrontendFiles(directory=settings.frontend_directory, html=True), name="frontend")
    return app
