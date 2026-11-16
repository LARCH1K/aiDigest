"""Начальная схема: cases, processed_urls, runs

Revision ID: 0001
Revises:
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE cases (
            id text PRIMARY KEY,
            level text NOT NULL,
            first_seen date NOT NULL,
            updated date NOT NULL,
            data jsonb NOT NULL
        )""")
    op.execute("""
        CREATE TABLE processed_urls (
            url text PRIMARY KEY,
            added timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute("""
        CREATE TABLE runs (
            id text PRIMARY KEY,
            state text NOT NULL,
            started timestamptz NOT NULL,
            finished timestamptz,
            exit_code integer,
            reason text,
            report jsonb NOT NULL DEFAULT '{}'::jsonb,
            params jsonb NOT NULL DEFAULT '{}'::jsonb
        )""")
    op.execute("CREATE UNIQUE INDEX runs_one_running ON runs ((true)) WHERE state = 'running'")


def downgrade() -> None:
    op.execute("DROP TABLE runs")
    op.execute("DROP TABLE processed_urls")
    op.execute("DROP TABLE cases")
