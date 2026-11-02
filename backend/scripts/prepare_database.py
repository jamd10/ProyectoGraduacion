"""Preparación local interactiva: nunca guardar ni imprimir contraseñas."""
import argparse
from getpass import getpass
from pathlib import Path
import sys

import psycopg
from psycopg import sql
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "src"))
DATABASE = "nexopass"
MIGRATOR = "nexopass_migrator"


def prepare_database(admin_password, migrator_password, *, host="localhost", port=5432):
    with psycopg.connect(host=host, port=port, user="postgres", password=admin_password,
                         dbname="postgres", autocommit=True, connect_timeout=10) as connection:
        existing_database = connection.execute(
            "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = %s", (DATABASE,)
        ).fetchone()
        if existing_database and existing_database[0] != MIGRATOR:
            raise RuntimeError("La base nexopass ya existe con otro propietario. No se modificó su propiedad.")
        existing_role = connection.execute(
            "SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
            "FROM pg_roles WHERE rolname = %s", (MIGRATOR,)
        ).fetchone()
        if existing_role and (not existing_role[0] or any(existing_role[1:])):
            raise RuntimeError("El rol existente no tiene el perfil esperado. No se modificaron sus permisos.")
        if existing_database and not existing_role:
            raise RuntimeError("Propiedad inconsistente; revisar manualmente antes de continuar.")
        if not existing_role:
            connection.execute(sql.SQL(
                "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
            ).format(sql.Identifier(MIGRATOR), sql.Literal(migrator_password)))
        else:
            # Verifica el secreto indicado; no cambia la contraseña del rol existente.
            with psycopg.connect(host=host, port=port, user=MIGRATOR, password=migrator_password,
                                 dbname="postgres", connect_timeout=10):
                pass
        if not existing_database:
            connection.execute(sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8' TEMPLATE template0").format(
                sql.Identifier(DATABASE), sql.Identifier(MIGRATOR)))
        # Privacidad de la base de aplicación, sin tocar otras bases ni pg_hba.conf.
        connection.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(DATABASE)))

    url = URL.create("postgresql+psycopg", username=MIGRATOR, password=migrator_password,
                     host=host, port=port, database=DATABASE)
    engine = create_engine(url, hide_parameters=True, connect_args={"connect_timeout": 10})
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        config = Config(str(ROOT / "alembic.ini"))
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            command.check(config)
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="Crea la base local de NexoPass y aplica sus migraciones.")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=5432)
    args = parser.parse_args()
    print("NexoPass: preparación local de PostgreSQL.")
    print("No se crean usuarios de la plataforma ni se modifica Git.")
    print("Las contraseñas se introducen ocultas y no se guardan en archivos.")
    admin_password = getpass("Contraseña de postgres (la del instalador): ")
    migrator_password = getpass("Contraseña para nexopass_migrator (nueva, o la existente si ya lo creaste): ")
    confirmation = getpass("Repite la contraseña de nexopass_migrator: ")
    if not admin_password or not migrator_password or confirmation != migrator_password:
        print("Contraseñas vacías o confirmación diferente. No se realizaron cambios.")
        return 1
    try:
        prepare_database(admin_password, migrator_password, host=args.host, port=args.port)
    except RuntimeError as error:
        print(str(error))
        return 1
    except Exception:
        # No volcar DSN, SQL ni parámetros que puedan contener credenciales.
        print("No se completó la preparación. Comprueba servicio, puerto, credenciales y versión de migración.")
        print("No se cambian contraseñas existentes. Si hubo creación parcial, puedes reintentar con los mismos datos.")
        return 1
    print("Base nexopass lista: migraciones aplicadas y modelo verificado.")
    print("Guarda la contraseña del migrador. La futura API utilizará otro rol con permisos limitados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
