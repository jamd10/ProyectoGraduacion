"""Arranque local interactivo: contraseña oculta y servidor solo en loopback."""
import argparse
from getpass import getpass
from pathlib import Path
import sys

from pydantic import SecretStr, ValidationError
import uvicorn

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from nexopass.app import create_app
from nexopass.config import Settings


def main():
    parser = argparse.ArgumentParser(description="Iniciar la API local de NexoPass.")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("El puerto debe estar entre 1 y 65535.")
    try:
        settings = Settings()
    except ValidationError:
        print("Configuración inválida. Revisa las variables NEXOPASS_ sin compartir credenciales.")
        return 1
    if settings.database_password is None or not settings.database_password.get_secret_value():
        password = getpass("Contraseña de nexopass_app: ")
        if not password:
            print("No se inició la API: falta la contraseña de conexión.")
            return 1
        settings = settings.model_copy(update={"database_password": SecretStr(password)})
    uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port, access_log=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
