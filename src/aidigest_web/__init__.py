"""Веб-фронт aiDigest для команды «Аналитика».

Отдельный пакет: из aidigest только читает данные, сбор запускает отдельным процессом.
Чтобы убрать фронт, достаточно удалить эту папку, tests/web и extra «web» в pyproject.toml.
"""
from __future__ import annotations

import secrets
from pathlib import Path

from flask import Flask

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def create_app(data_dir: Path, password: str | None, secret_key: str | None = None, run_manager=None) -> Flask:
    from aidigest_web import auth, routes
    from aidigest_web.runs import RunManager

    app = Flask(__name__)
    app.config["DATA_DIR"] = Path(data_dir)
    app.config["WEB_PASSWORD"] = password or None
    app.secret_key = secret_key or secrets.token_hex(32)
    app.extensions["runs"] = run_manager or RunManager(Path(data_dir), PROJECT_ROOT)
    auth.init(app)
    routes.init(app)
    return app
