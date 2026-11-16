"""Окружение alembic: только online-режим."""
from alembic import context
from sqlalchemy import create_engine

from aidigest.db.engine import database_url
from aidigest.db.schema import metadata


def run() -> None:
    connection = context.config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, target_metadata=metadata)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(database_url())
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=metadata)
        with context.begin_transaction():
            context.run_migrations()
        conn.commit()


run()
