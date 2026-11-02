"""Provisionar exclusivamente el rol de ejecución local de NexoPass.

No concede escritura ni acceso a datos privados: por ahora solo hay salud.
Las futuras funciones de negocio deberán añadir permisos de forma explícita.
"""
import argparse
from getpass import getpass
import re

import psycopg
from psycopg import sql

ROLE = "nexopass_app"


def provision_runtime(admin_password, runtime_password, *, database="nexopass", host="127.0.0.1", port=5432):
    if database != "nexopass" and not re.fullmatch(r"nexopass_test_[a-z0-9_]+", database):
        raise ValueError("La base debe pertenecer a NexoPass.")
    if not runtime_password:
        raise ValueError("La contraseña del usuario de ejecución es obligatoria.")
    with psycopg.connect(host=host, port=port, user="postgres", password=admin_password,
                         dbname=database, connect_timeout=5) as admin:
        owner = admin.execute("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database()").fetchone()[0]
        if owner != "nexopass_migrator":
            raise RuntimeError("Propietario inesperado; no se alteraron permisos.")
        role = admin.execute("SELECT oid, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls FROM pg_roles WHERE rolname=%s", (ROLE,)).fetchone()
        if role:
            if not role[1] or any(role[2:]):
                raise RuntimeError("El rol existente tiene atributos incompatibles; no se modificó.")
            if admin.execute("SELECT EXISTS(SELECT 1 FROM pg_auth_members WHERE member=%s)", (role[0],)).fetchone()[0]:
                raise RuntimeError("El rol tiene membresías inesperadas; revisar manualmente.")
            with psycopg.connect(host=host, port=port, user=ROLE, password=runtime_password,
                                 dbname="postgres", connect_timeout=5):
                pass
        else:
            admin.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}").format(sql.Identifier(ROLE), sql.Literal(runtime_password)))
        admin.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(database), sql.Identifier(ROLE)))
        admin.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(ROLE)))
        admin.execute(sql.SQL("GRANT SELECT ON TABLE public.alembic_version TO {}").format(sql.Identifier(ROLE)))
        # No conceder permisos por defecto para tablas futuras ni usar ALL TABLES.
        unsafe = admin.execute("""
            SELECT EXISTS (
                SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m') AND (
                    has_table_privilege(%s,c.oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
                    OR (c.relname <> 'alembic_version' AND has_table_privilege(%s,c.oid,'SELECT'))
                )
            ) OR has_schema_privilege(%s,'public','CREATE')
              OR has_database_privilege(%s,current_database(),'CREATE,TEMP')
        """, (ROLE, ROLE, ROLE, ROLE)).fetchone()[0]
        # Las bases nuevas de PostgreSQL suelen conceder TEMP a PUBLIC.
        # Se revoca únicamente en la base NexoPass seleccionada.
        if unsafe:
            admin.execute(sql.SQL("REVOKE TEMPORARY ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database)))
            unsafe = admin.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                    WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m') AND (
                        has_table_privilege(%s,c.oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
                        OR (c.relname <> 'alembic_version' AND has_table_privilege(%s,c.oid,'SELECT'))
                    )
                ) OR has_schema_privilege(%s,'public','CREATE')
                  OR has_database_privilege(%s,current_database(),'CREATE,TEMP')
            """, (ROLE, ROLE, ROLE, ROLE)).fetchone()[0]
            if unsafe:
                raise RuntimeError("El rol conserva privilegios inesperados; se revierte la operación.")


def main():
    parser = argparse.ArgumentParser(description="Preparar el usuario limitado de NexoPass.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5432)
    args = parser.parse_args()
    admin = getpass("Contraseña de postgres: ")
    password = getpass("Contraseña de nexopass_app (nueva o existente): ")
    if password != getpass("Repite la contraseña de nexopass_app: "):
        print("La confirmación no coincide. No se realizaron cambios.")
        return 1
    try:
        provision_runtime(admin, password, host=args.host, port=args.port)
    except Exception:
        print("No se pudo provisionar el rol; revisa credenciales, migraciones y permisos. No se cambian contraseñas existentes.")
        return 1
    print("nexopass_app listo: conexión y lectura de revisión, sin acceso a datos privados ni cambios de estructura.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
