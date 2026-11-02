"""Respaldo y restauración verificable a una base nueva; nunca sobrescribe nexopass."""
import argparse
from datetime import datetime, timezone
from getpass import getpass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
from uuid import uuid4

import psycopg
from psycopg import sql

PROJECT = Path(__file__).resolve().parents[2]
BIN = Path(r"C:\Program Files\PostgreSQL\18\bin")


def postgres_command(name, arguments, password):
    executable = shutil.which(name) or str(BIN / (name + ".exe"))
    env = os.environ.copy()
    env["PGPASSWORD"] = password
    env["PGCONNECTTIMEOUT"] = "5"
    result = subprocess.run([executable, *arguments], env=env, capture_output=True)
    if result.returncode:
        raise RuntimeError("La herramienta de PostgreSQL no completó la operación.")


def allowed_database(name):
    if name != "nexopass" and not re.fullmatch(r"nexopass_test_[a-z0-9_]+", name):
        raise ValueError("Solo se admiten bases de NexoPass.")


def outside_project(path):
    result = Path(path).resolve()
    if result.is_relative_to(PROJECT):
        raise ValueError("Los respaldos y claves deben quedar fuera del repositorio.")
    return result


def signature(file):
    hasher = sha256()
    with file.open("rb") as stream:
        for part in iter(lambda: stream.read(1024*1024), b""):
            hasher.update(part)
    return hasher.hexdigest()


def create_backup(password, *, database="nexopass", state_directory=None, output_directory=None):
    allowed_database(database)
    state = outside_project(state_directory or Path.home()/"NexoPassData")
    if (state/"app.lock").exists():
        raise RuntimeError("Detén NexoPass antes de crear el respaldo.")
    with socket.socket() as probe:
        probe.settimeout(0.2)
        if probe.connect_ex(("127.0.0.1",8545))==0:
            raise RuntimeError("Detén la cadena local del puerto 8545 antes del respaldo.")
    output = outside_project(output_directory or Path.home()/"NexoPassBackups")
    if output.is_relative_to(state):
        raise ValueError("La carpeta de respaldos no puede estar dentro de los datos originales.")
    output.mkdir(parents=True,exist_ok=True)
    target = output / ("nexopass-"+datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")+"-"+uuid4().hex[:6])
    target.mkdir()
    with psycopg.connect(host="127.0.0.1",dbname=database,user="nexopass_migrator",password=password) as connection:
        tables = [r[0] for r in connection.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
        # Bloquea escrituras durante el dump; no incluye bloqueos de la cadena, que debe estar detenida.
        if tables:
            connection.execute(sql.SQL("LOCK TABLE {} IN SHARE MODE").format(sql.SQL(",").join(sql.Identifier("public", t) for t in tables)))
        counts={t:connection.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier("public",t))).fetchone()[0] for t in tables}
        revision=connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        postgres_command("pg_dump",["--format=custom","--no-password","--host=127.0.0.1","--username=nexopass_migrator",
            "--dbname="+database,"--file="+str(target/"database.dump")],password)
        if state.exists():
            shutil.copytree(state,target/"state",ignore=shutil.ignore_patterns("*.log","app.lock"))
    files={str(file.relative_to(target)).replace("\\","/"):signature(file) for file in target.rglob("*") if file.is_file()}
    (target/"manifest.json").write_text(json.dumps({"format":1,"revision":revision,"counts":counts,"files":files},indent=2),encoding="utf-8")
    return target


def restore_backup(backup, admin_password, migrator_password, *, database, output_directory=None):
    if not re.fullmatch(r"nexopass_test_restore_[a-z0-9_]+",database):
        raise ValueError("La restauración requiere una base nueva nexopass_test_restore_*. Nunca sobrescribe nexopass.")
    source=outside_project(backup)
    manifest=json.loads((source/"manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format")!=1:
        raise ValueError("Formato de respaldo no admitido.")
    for name,expected in manifest["files"].items():
        file=(source/name).resolve()
        if not file.is_relative_to(source) or not file.is_file() or file.is_symlink() or signature(file)!=expected:
            raise ValueError("El respaldo no supera la verificación de integridad.")
    target=outside_project(output_directory or Path.home()/("NexoPassRestore-"+uuid4().hex[:8]))
    if target.exists():
        raise ValueError("La carpeta de restauración ya existe; no se sobrescribe.")
    with psycopg.connect(host="127.0.0.1",dbname="postgres",user="postgres",password=admin_password,autocommit=True) as admin:
        if admin.execute("SELECT 1 FROM pg_database WHERE datname=%s",(database,)).fetchone():
            raise ValueError("La base de restauración ya existe; no se modifica.")
        admin.execute(sql.SQL("CREATE DATABASE {} OWNER nexopass_migrator").format(sql.Identifier(database)))
        try:
            postgres_command("pg_restore",["--no-password","--host=127.0.0.1","--username=nexopass_migrator","--no-owner","--no-privileges",
                "--single-transaction","--exit-on-error","--dbname="+database,str(source/"database.dump")],migrator_password)
            with psycopg.connect(host="127.0.0.1",dbname=database,user="postgres",password=admin_password) as connection:
                for table,count in manifest["counts"].items():
                    if connection.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier("public",table))).fetchone()[0]!=count:
                        raise RuntimeError("El recuento restaurado no coincide.")
                if connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]!=manifest["revision"]:
                    raise RuntimeError("La revisión restaurada no coincide.")
            if (source/"state").exists():
                shutil.copytree(source/"state",target)
            else:
                target.mkdir(parents=True)
        except Exception:
            # Solo la base NUEVA creada por esta misma llamada; nunca una preexistente.
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))
            raise
    return target


def main():
    parser=argparse.ArgumentParser(description="Respaldo y restauración aislada de NexoPass.")
    parser.add_argument("action",choices=["create","restore"])
    parser.add_argument("--backup")
    parser.add_argument("--database",default="nexopass")
    args=parser.parse_args()
    try:
        if args.action=="create":
            target=create_backup(getpass("Contraseña de nexopass_migrator: "),database=args.database)
        else:
            if not args.backup:
                raise ValueError("Indica --backup con la carpeta del respaldo.")
            target=restore_backup(args.backup,getpass("Contraseña de postgres: "),getpass("Contraseña de nexopass_migrator: "),database=args.database)
        print("Operación verificada. Carpeta:",target)
        print("Resguarda la carpeta: incluye las claves necesarias para recuperar los datos cifrados.")
    except Exception as error:
        if isinstance(error,(ValueError,RuntimeError)):
            print(str(error))
        else:
            print("No se completó el respaldo o restauración. Revisa rutas, servicios y credenciales.")
        return 1
    return 0


if __name__=="__main__":
    raise SystemExit(main())
