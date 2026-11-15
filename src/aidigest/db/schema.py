"""Схема базы (SQLAlchemy Core)."""
from __future__ import annotations

from sqlalchemy import (
    Column, Date, DateTime, Index, Integer, MetaData, Table, Text, func, text, true,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

cases = Table(
    "cases", metadata,
    Column("id", Text, primary_key=True),
    Column("level", Text, nullable=False),
    Column("first_seen", Date, nullable=False),
    Column("updated", Date, nullable=False),
    Column("data", JSONB, nullable=False),
)

processed_urls = Table(
    "processed_urls", metadata,
    Column("url", Text, primary_key=True),
    Column("added", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

runs = Table(
    "runs", metadata,
    Column("id", Text, primary_key=True),
    Column("state", Text, nullable=False),
    Column("started", DateTime(timezone=True), nullable=False),
    Column("finished", DateTime(timezone=True)),
    Column("exit_code", Integer),
    Column("reason", Text),
    Column("report", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("params", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    # не более одного запуска в состоянии running
    Index("runs_one_running", true(), unique=True, postgresql_where=text("state = 'running'")),
)
