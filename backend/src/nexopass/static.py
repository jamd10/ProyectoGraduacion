"""Frontend SPA y medios locales, separados de las rutas de la API."""
from pathlib import Path
from fastapi import HTTPException
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles


class FrontendFiles(StaticFiles):
    async def get_response(self, path, scope):
        path = path.replace("\\", "/").lstrip("/")
        if path.startswith("api/") or path in ("docs", "redoc", "openapi.json"):
            raise HTTPException(404, "No encontrado")
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as error:
            if error.status_code != 404 or Path(path).suffix:
                raise
            return await super().get_response("index.html", scope)


class UploadBodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/v1/images/"):
            return await self.app(scope, receive, send)
        size = 0
        async def limited_receive():
            nonlocal size
            message = await receive()
            if message["type"] == "http.request":
                size += len(message.get("body", b""))
                if size > 6*1024*1024:
                    raise StarletteHTTPException(413, "La carga supera el límite permitido")
            return message
        await self.app(scope, limited_receive, send)
