import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from aidigest.db.engine import migrate

pytestmark = pytest.mark.pg


def test_tables_exist(pg):
    assert {"cases", "processed_urls", "runs"} <= set(inspect(pg).get_table_names())


def test_migrate_is_idempotent(pg):
    migrate(pg)
    migrate(pg)


def test_only_one_running_run(pg):
    ins = text("INSERT INTO runs (id, state, started) VALUES (:id, 'running', now())")
    with pg.begin() as c:
        c.execute(ins, {"id": "a"})
    with pytest.raises(IntegrityError):
        with pg.begin() as c:
            c.execute(ins, {"id": "b"})
