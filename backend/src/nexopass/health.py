"""Salud sin datos de infraestructura, consultas ni excepciones en respuestas."""
import logging
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/v1/health", tags=["Health"])
logger = logging.getLogger(__name__)
# Actualizar al incorporar una migración requerida por la aplicación.
REQUIRED_SCHEMA_REVISION = "0006"


class HealthResponse(BaseModel):
    status: Literal["ok", "ready", "not_ready"]


def health_response(status: str, status_code: int = 200) -> JSONResponse:
    return JSONResponse({"status": status}, status_code=status_code, headers={"Cache-Control": "no-store"})


@router.get("/live", response_model=HealthResponse)
def live():
    """La API responde. No realiza consultas ni depende de PostgreSQL."""
    return health_response("ok")


@router.get("/ready", response_model=HealthResponse, responses={503: {"model": HealthResponse}})
def ready(request: Request):
    """Lista para servir solo con conexión y revisión compatibles."""
    engine = request.app.state.database
    if engine is None:
        return health_response("not_ready", 503)
    try:
        with engine.connect() as connection:
            revision = connection.execute(text(
                "SELECT current_user AS runtime_user, version_num FROM public.alembic_version"
            )).mappings().one_or_none()
        if revision is None or revision["runtime_user"] != "nexopass_app" or revision["version_num"] != REQUIRED_SCHEMA_REVISION:
            logger.warning("readiness_schema_or_role_incompatible")
            return health_response("not_ready", 503)
    except SQLAlchemyError:
        # No registrar la excepción: puede incluir SQL, host o credenciales.
        logger.warning("readiness_database_unavailable")
        return health_response("not_ready", 503)
    return health_response("ready")
