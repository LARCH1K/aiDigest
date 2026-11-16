"""Подключение к Postgres и применение миграций."""
from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine

DEFAULT_URL = "postgresql+psycopg://aidigest:aidigest@localhost:5433/aidigest"


def database_url() -> str:
    return os.environ.get("DATABASE_URL") or DEFAULT_URL


def make_engine(url: str | None = None) -> Engine:
    return create_engine(url or database_url(), pool_pre_ping=True)


def migrate(engine: Engine) -> None:
    """alembic upgrade head; не зависит от текущего каталога."""
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "head")
