"""La conexión procede del entorno o del objeto connection para pruebas."""
import os

from alembic import context
from sqlalchemy import create_engine, pool
from nexopass.schema import metadata

config = context.config


def configure(connection):
    context.configure(connection=connection, target_metadata=metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(url="postgresql+psycopg://", target_metadata=metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()
else:
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        configure(supplied_connection)
    else:
        database_url = os.environ.get("NEXOPASS_DATABASE_URL")
        if not database_url:
            raise RuntimeError("Falta NEXOPASS_DATABASE_URL; no se usa postgres por defecto.")
        engine = create_engine(database_url, poolclass=pool.NullPool, hide_parameters=True)
        try:
            with engine.connect() as connection:
                configure(connection)
        finally:
            engine.dispose()
