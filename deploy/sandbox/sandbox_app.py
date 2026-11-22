"""Точка входа aiDigest для песочницы с appctl."""
import os
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import FileResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from aidigest.creds import SECRETS_FILE, WEB_KEYS, load_creds
from aidigest.db.engine import make_engine
from aidigest_api import create_app


def mount_frontend(api, dist: Path):
    index = dist / "index.html"
    if not index.is_file():
        raise RuntimeError("Не найден собранный фронтенд")

    async def spa(request):
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    frontend = Starlette(routes=[
        Mount("/assets", app=StaticFiles(directory=dist / "assets")),
        Route("/{path:path}", spa),
    ])

    async def application(scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or path in {"/api", "/healthz"} or path.startswith("/api/"):
            await api(scope, receive, send)
        else:
            await frontend(scope, receive, send)

    return application


def create_application():
    release = Path(__file__).resolve().parent
    credentials = load_creds(release / SECRETS_FILE, WEB_KEYS)
    if any(not credentials.get(key) for key in WEB_KEYS):
        raise RuntimeError("Задайте WEB_USERNAME, WEB_PASSWORD и WEB_SECRET_KEY")

    api = create_app(
        make_engine(),
        username=credentials["WEB_USERNAME"],
        password=credentials["WEB_PASSWORD"],
        secret_key=credentials["WEB_SECRET_KEY"],
        secure_cookie=True,
        data_dir=Path(os.environ["AIDIGEST_DATA_DIR"]),
    )
    return mount_frontend(api, release / "frontend" / "dist")
