"""Preparación y ejecución local de NexoPass. Contraseñas solo en memoria."""
import argparse
from datetime import datetime, timedelta, timezone
from getpass import getpass
import json
import os
from pathlib import Path
import runpy
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "backend" / "src"))
TOOLS = Path.home() / "NexoPassTools"


def node_paths():
    candidates = [TOOLS / "node-v26.13.0-win-x64" / "node.exe", Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "nodejs" / "node.exe"]
    if shutil.which("node"):
        candidates.append(Path(shutil.which("node")))
    for node in candidates:
        npm = node.parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
        if node.is_file() and npm.is_file():
            return node, npm
    raise RuntimeError("Instala Node.js LTS para preparar el frontend y los contratos.")


def build():
    node, npm = node_paths()
    environment = os.environ.copy()
    environment["PATH"] = str(node.parent) + os.pathsep + environment.get("PATH", "")
    environment["NODE_USE_SYSTEM_CA"] = "1"
    for package in ("contracts", "frontend"):
        subprocess.run([str(node), str(npm), "ci", "--no-audit", "--no-fund"], cwd=ROOT/package, env=environment, check=True)
    subprocess.run([str(node), str(ROOT/"contracts"/"compile.mjs")], cwd=ROOT/"contracts", env=environment, check=True)
    subprocess.run([str(node), str(npm), "run", "build"], cwd=ROOT/"frontend", env=environment, check=True)


def create_admin(connection, email, password, data_directory):
    from sqlalchemy import select, update
    from sqlalchemy.dialects.postgresql import insert
    from pydantic import TypeAdapter, EmailStr
    from eth_account import Account
    from nexopass import schema as s
    from nexopass.security import hasher, local_cipher
    email = str(TypeAdapter(EmailStr).validate_python(email)).lower()
    if len(password) < 10:
        raise ValueError("La contraseña del administrador debe tener al menos diez caracteres.")
    existing = connection.execute(select(s.users).where(s.users.c.email == email)).mappings().one_or_none()
    if existing:
        is_admin = connection.execute(select(s.user_roles).where(s.user_roles.c.user_id == existing["id"], s.user_roles.c.role_code == "admin")).first()
        if is_admin:
            print("La cuenta administrativa ya existe; su contraseña no se modificó.")
            return existing["id"]
        raise RuntimeError("Ese correo ya pertenece a una cuenta normal. No se eleva automáticamente.")
    if not (data_directory/"master.key").exists() and connection.execute(select(s.wallets.c.id).where(s.wallets.c.encrypted_private_key.is_not(None)).limit(1)).first():
        raise RuntimeError("Falta master.key para los datos existentes. Restaura su respaldo antes de continuar.")
    user_id = connection.execute(s.users.insert().values(email=email, full_name="Administración NexoPass",
        password_hash=hasher.hash(password), email_verified_at=datetime.now(timezone.utc)).returning(s.users.c.id)).scalar_one()
    account = Account.create()
    connection.execute(s.wallets.insert().values(user_id=user_id, address=account.address.lower(), kind="embedded",
        verified_at=datetime.now(timezone.utc), encrypted_private_key=local_cipher(str(data_directory)).encrypt(bytes(account.key))))
    connection.execute(insert(s.roles).values(code="admin").on_conflict_do_nothing())
    connection.execute(s.user_roles.insert().values(user_id=user_id, role_code="admin"))
    return user_id


def seed_demo(connection):
    from decimal import Decimal
    from sqlalchemy import select
    from nexopass import schema as s
    existing = connection.execute(select(s.events.c.id).where(s.events.c.name.like("%[DEMO]%")).limit(1)).first()
    if existing:
        print("La cartelera de demostración ya existe; no se duplicó.")
        return
    venue = connection.execute(s.venues.insert().values(name="Arena Nexo [DEMO]", city="Tegucigalpa",
        address="Recinto ficticio de demostración", timezone="America/Tegucigalpa").returning(s.venues.c.id)).scalar_one()
    now = datetime.now(timezone.utc)
    for index, name in enumerate(("Nexo Sessions [DEMO]", "Horizonte Live [DEMO]", "Ritmos al aire [DEMO]")):
        starts = now+timedelta(hours=2) if index==0 else now+timedelta(days=3+index)
        doors = now-timedelta(minutes=10) if index==0 else starts-timedelta(hours=1)
        event = connection.execute(s.events.insert().values(venue_id=venue, name=name, status="published",
            description="Concierto ficticio para demostrar NexoPass. No corresponde a una venta ni a un evento real.",
            starts_at=starts, ends_at=starts+timedelta(hours=4), doors_open_at=doors,
            sales_open_at=now-timedelta(days=1), sales_close_at=starts-timedelta(minutes=15), transfer_deadline=starts-timedelta(days=1)).returning(s.events.c.id)).scalar_one()
        for order, (name, mode, capacity, price) in enumerate((("Platinum","seated",30,950),("VIP","seated",40,650),("General","general",60,250))):
            zone = connection.execute(s.zones.insert().values(event_id=event,name=name,mode=mode,price=Decimal(price),currency="HNL",
                display_order=order,benefits="Zona de demostración; revisa tu ubicación antes de comprar.").returning(s.zones.c.id)).scalar_one()
            units=[]
            for number in range(capacity):
                row,seat=divmod(number,10)
                units.append(dict(event_id=event,zone_id=zone,mode=mode,unit_number=number+1,
                    row_label=str(row+1) if mode=="seated" else None,seat_label=str(seat+1) if mode=="seated" else None,
                    map_x=Decimal(str(round((seat+1)/11,6))) if mode=="seated" else None,
                    map_y=Decimal(str(round((row+1)/(capacity//10+1),6))) if mode=="seated" else None))
            connection.execute(s.inventory_units.insert(),units)
    print("Cartelera ficticia creada; no se emitieron ventas ni NFT de ejemplo.")


def setup(no_build=False):
    from sqlalchemy import create_engine
    from sqlalchemy.engine import URL
    from nexopass.config import Settings
    if not no_build:
        build()
    admin_password = getpass("Contraseña de postgres: ")
    migrator_password = getpass("Contraseña de nexopass_migrator: ")
    runtime_password = getpass("Contraseña de nexopass_app: ")
    prepare=runpy.run_path(str(ROOT/"backend"/"scripts"/"prepare_database.py"))["prepare_database"]
    prepare(admin_password,migrator_password)
    runpy.run_path(str(ROOT/"backend"/"scripts"/"prepare_runtime.py"))["provision_runtime"](admin_password,runtime_password)
    email=input("Correo del administrador [nexopass@proton.me]: ").strip() or "nexopass@proton.me"
    password=getpass("Contraseña del administrador de la plataforma (mínimo 10 caracteres): ")
    if password != getpass("Confirma la contraseña del administrador: "):
        raise RuntimeError("Las contraseñas no coinciden.")
    engine=create_engine(URL.create("postgresql+psycopg",username="nexopass_migrator",password=migrator_password,host="127.0.0.1",database="nexopass"),hide_parameters=True)
    try:
        with engine.begin() as connection:
            create_admin(connection,email,password,Settings().data_directory)
            if input("¿Crear conciertos ficticios para la demostración? [s/N]: ").strip().lower()=="s":
                seed_demo(connection)
    finally:
        engine.dispose()
    print("Preparación completa. Las contraseñas no se guardaron en archivos.")


def port_open(port):
    with socket.socket() as probe:
        probe.settimeout(0.2)
        return probe.connect_ex(("127.0.0.1",port))==0


def rpc(method, params=None):
    payload=json.dumps({"jsonrpc":"2.0","id":1,"method":method,"params":params or []}).encode()
    with urlopen(Request("http://127.0.0.1:8545",data=payload,headers={"Content-Type":"application/json"}),timeout=2) as response:
        return json.load(response).get("result")


def run(port=8000, open_browser=True):
    from pydantic import SecretStr
    from sqlalchemy import text
    from nexopass.config import Settings
    from nexopass.database import create_database_engine
    from nexopass.app import create_app
    import uvicorn
    if port_open(port):
        raise RuntimeError(f"El puerto {port} está ocupado. No se detuvo el otro servicio.")
    if not (ROOT/"frontend"/"dist"/"index.html").is_file() or not (ROOT/"contracts"/"artifacts"/"NexoPass.json").is_file():
        raise RuntimeError("Falta compilar. Ejecuta preparar.cmd antes de iniciar.")
    settings=Settings()
    if not settings.database_password:
        value=getpass("Contraseña de nexopass_app: ")
        if not value:
            raise RuntimeError("Falta la contraseña de la base.")
        settings=settings.model_copy(update={"database_password":SecretStr(value)})
    if settings.smtp_user and not settings.smtp_password:
        settings=settings.model_copy(update={"smtp_password":SecretStr(getpass("Credencial SMTP del servicio de envío: "))})
    if "NEXOPASS_PUBLIC_URL" not in os.environ:
        settings=settings.model_copy(update={"public_url":f"http://127.0.0.1:{port}"})
    engine=create_database_engine(settings)
    try:
        with engine.connect() as connection:
            role,revision=connection.execute(text("SELECT current_user,version_num FROM public.alembic_version")).one()
            if role!="nexopass_app" or revision!="0005":
                raise RuntimeError("Revisa el usuario o aplica las migraciones pendientes.")
    finally:
        engine.dispose()
    settings.data_directory.mkdir(parents=True,exist_ok=True)
    process=None
    log=None
    lock=settings.data_directory/"app.lock"
    if lock.exists():
        raise RuntimeError("Hay una marca de ejecución previa. Comprueba que NexoPass esté detenido antes de retirar NexoPassData/app.lock.")
    lock.write_text(str(os.getpid()))
    try:
        if settings.chain_id==31337 and settings.chain_rpc_url=="http://127.0.0.1:8545":
            if port_open(8545):
                deployment=settings.data_directory/"deployment.json"
                if not deployment.exists() or int(rpc("eth_chainId"),16)!=31337 or rpc("eth_getCode",[json.loads(deployment.read_text())["address"],"latest"])=="0x":
                    raise RuntimeError("El puerto 8545 pertenece a otro servicio. No se reutiliza ni modifica.")
            else:
                node,_=node_paths()
                log=(settings.data_directory/"chain.log").open("ab")
                child_env=os.environ.copy()
                child_env["NEXOPASS_DATA_DIRECTORY"]=str(settings.data_directory)
                for secret_name in ("NEXOPASS_DATABASE_PASSWORD","NEXOPASS_SMTP_PASSWORD","NEXOPASS_RELAYER_KEY"):child_env.pop(secret_name,None)
                process=subprocess.Popen([str(node),str(ROOT/"contracts"/"chain.mjs")],cwd=ROOT/"contracts",stdout=log,stderr=log,env=child_env,stdin=subprocess.PIPE,text=True)
                deadline=time.monotonic()+20
                while not port_open(8545):
                    if process.poll() is not None or time.monotonic()>deadline:
                        raise RuntimeError("No inició la cadena local. Revisa NexoPassData/chain.log.")
                    time.sleep(0.2)
                if int(rpc("eth_chainId"),16)!=31337:
                    raise RuntimeError("La cadena iniciada no corresponde al proyecto.")
        if open_browser:
            import threading
            threading.Timer(1.5,lambda:webbrowser.open(settings.public_url)).start()
        print("NexoPass local listo. Usa Ctrl+C para detener la aplicación.")
        uvicorn.run(create_app(settings),host="127.0.0.1",port=port,access_log=False)
    finally:
        if process and process.poll() is None:
            try:
                process.stdin.write("shutdown\n")
                process.stdin.flush()
                process.wait(timeout=10)
            except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)
        if log:
            log.close()
        lock.unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser(description="NexoPass: preparación y ejecución local.")
    parser.add_argument("action",choices=["setup","run","build"])
    parser.add_argument("--port",type=int,default=8000)
    parser.add_argument("--no-browser",action="store_true")
    parser.add_argument("--no-build",action="store_true")
    args=parser.parse_args()
    try:
        if args.action=="setup":setup(args.no_build)
        elif args.action=="build":build()
        elif not 1<=args.port<=65535:raise ValueError("Puerto inválido")
        else:run(args.port,not args.no_browser)
    except KeyboardInterrupt:
        print("NexoPass detenido.")
    except Exception as error:
        # No imprimir excepciones de conexiones ni SQL con credenciales.
        if isinstance(error,(RuntimeError,ValueError)):
            print(str(error))
        else:
            print("No se completó la operación. Revisa servicios, dependencias y credenciales; no las compartas por chat.")
        return 1
    return 0


if __name__=="__main__":
    raise SystemExit(main())
