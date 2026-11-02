"""Conexión de ejecución: sin DDL, credenciales implícitas ni migraciones."""
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, URL

from nexopass.config import Settings


def create_database_engine(settings: Settings) -> Engine | None:
    password = settings.database_password
    if password is None or not password.get_secret_value():
        return None
    url = URL.create(
        "postgresql+psycopg", username=settings.database_user,
        password=password.get_secret_value(), host=settings.database_host,
        port=settings.database_port, database=settings.database_name,
    )
    return create_engine(
        url, pool_pre_ping=True, pool_size=5, max_overflow=5, pool_timeout=3,
        pool_recycle=300, hide_parameters=True, echo=False,
        connect_args={"connect_timeout": settings.database_connect_timeout,
                      "options": "-c statement_timeout=3000 -c lock_timeout=2000"},
    )
