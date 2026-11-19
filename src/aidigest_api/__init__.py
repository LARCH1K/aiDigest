"""HTTP API aiDigest для фронтенда и других клиентов."""
import json
from contextlib import asynccontextmanager
from pathlib import Path
from secrets import token_hex

from fastapi import FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import PlainTextResponse
from sqlalchemy import Engine

from aidigest.config import Settings, load_settings
from aidigest.creds import SECRETS_FILE, TAVILY_KEYS, load_creds
from aidigest.db.engine import migrate
from aidigest.search import search_provider
from aidigest.services.cases import CaseService
from aidigest.services.catalog import CONFIG_ERRORS, CatalogService
from aidigest.services.runs import RunService, RunStore
from aidigest.store import PgCaseStore
from aidigest_api.auth import install_auth
from aidigest_api.routes import api_routes

ROOT = Path(__file__).resolve().parents[2]


def create_app(engine: Engine, *, username: str | None, password: str | None, secret_key: str | None,
               secure_cookie: bool = False, config_dir: Path | None = None, data_dir: Path | None = None,
               run_service: RunService | None = None, trust_real_ip: bool = False) -> FastAPI:
    config_dir = config_dir if config_dir is not None else ROOT / "config"
    if run_service is None:
        try:
            settings = load_settings(config_dir / "settings.yaml")
        except CONFIG_ERRORS:
            settings = Settings()
        token = None
        if search_provider() == "tavily":
            token = load_creds(ROOT / SECRETS_FILE, TAVILY_KEYS).get("TAVILY_TOKEN")
        run_service = RunService(RunStore(engine), data_dir or ROOT / "data", ROOT, settings, token)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        migrate(engine)
        run_service.on_startup()
        try:
            yield
        finally:
            await run_in_threadpool(run_service.on_shutdown)

    app = FastAPI(title="aiDigest API", lifespan=lifespan, redirect_slashes=False)
    app.state.run_service = run_service
    install_auth(app, username=username, password=password, secret_key=secret_key or token_hex(32),
                 secure_cookie=secure_cookie, trust_real_ip=trust_real_ip)
    app.include_router(api_routes(CaseService(PgCaseStore(engine)), CatalogService(config_dir), run_service))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> Response:
        # Исходные значения могут содержать пароль или числа, которые нельзя сериализовать в JSON.
        details = [{key: error[key] for key in ("type", "loc", "msg")} for error in exc.errors()]
        return Response(json.dumps({"detail": details}), media_type="application/json", status_code=422)

    @app.get("/healthz", response_class=PlainTextResponse)
    def health() -> str:
        return "ok"

    return app
