"""Фикстуры Postgres; подключаются через pytest_plugins в tests/conftest.py."""
import os

import pytest
from sqlalchemy import text


@pytest.fixture(scope="session")
def pg_engine():
    url = os.environ.get("AIDIGEST_TEST_DATABASE_URL")
    if not url:
        pytest.skip("нет AIDIGEST_TEST_DATABASE_URL")
    from aidigest.db.engine import make_engine, migrate
    engine = make_engine(url)
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    migrate(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def pg(pg_engine):
    with pg_engine.begin() as c:
        c.execute(text("TRUNCATE cases, processed_urls, runs"))
    return pg_engine
