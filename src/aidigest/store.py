"""База кейсов: протокол Store, реализация в памяти (тесты) и в Postgres."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection, Engine

from aidigest.db.schema import cases as cases_table
from aidigest.db.schema import processed_urls as urls_table
from aidigest.models import Case

# Один ключ PostgreSQL для всех команд, меняющих базу кейсов.
_CASE_WRITER_LOCK = 0x4149444947455354


class WriterBusy(Exception):
    """Другой процесс уже меняет базу кейсов."""


@dataclass
class StoreData:
    cases: list[Case] = field(default_factory=list)
    processed_urls: set[str] = field(default_factory=set)


class Store(Protocol):
    def load(self) -> StoreData: ...
    def industry_names(self) -> set[str]: ...

    def save(self, data: StoreData) -> None: ...

    def write_lock(self) -> AbstractContextManager[Store]: ...


class MemoryStore:
    """Хранит глубокую копию, чтобы тесты ловили «забыли save»."""

    def __init__(self, data: StoreData | None = None):
        self._data = self._copy(data or StoreData())

    @staticmethod
    def _copy(data: StoreData) -> StoreData:
        return StoreData([c.model_copy(deep=True) for c in data.cases], set(data.processed_urls))

    def load(self) -> StoreData:
        return self._copy(self._data)

    def industry_names(self) -> set[str]:
        return {case.industry for case in self._data.cases}

    def save(self, data: StoreData) -> None:
        incoming = self._copy(data)
        cases = {case.id: case for case in self._data.cases}
        cases.update((case.id, case) for case in incoming.cases)
        self._data = StoreData(list(cases.values()), self._data.processed_urls | incoming.processed_urls)

    def write_lock(self) -> AbstractContextManager[Store]:
        return nullcontext(self)


class PgCaseStore:
    def __init__(self, engine: Engine, *, connection: Connection | None = None):
        self.engine = engine
        self._connection = connection

    @contextmanager
    def write_lock(self) -> Iterator[Store]:
        """Держит блокировку между транзакциями и освобождает её с закрытием сессии."""
        from aidigest.db.engine import migrate

        with self.engine.connect() as conn:
            # Закрыть физическую сессию, а не вернуть её с блокировкой в пул.
            conn.detach()
            with conn.begin():
                acquired = conn.execute(select(func.pg_try_advisory_lock(_CASE_WRITER_LOCK))).scalar_one()
                if not acquired:
                    raise WriterBusy
            migrate(self.engine)
            yield PgCaseStore(self.engine, connection=conn)

    @contextmanager
    def _transaction(self) -> Iterator[Connection]:
        if self._connection is None:
            with self.engine.begin() as conn:
                yield conn
        else:
            # С потерянным соединением потеряна и блокировка. Запись через новую сессию небезопасна.
            if self._connection.invalidated:
                raise RuntimeError("Соединение с блокировкой записи потеряно")
            with self._connection.begin():
                yield self._connection

    def load(self) -> StoreData:
        with self._transaction() as c:
            rows = c.execute(select(cases_table.c.data).order_by(cases_table.c.first_seen, cases_table.c.id))
            cases = [Case.model_validate(r[0]) for r in rows]
            urls = {r[0] for r in c.execute(select(urls_table.c.url))}
        return StoreData(cases, urls)

    def industry_names(self) -> set[str]:
        industry = cases_table.c.data["industry"].astext
        with self._transaction() as conn:
            return set(conn.scalars(select(industry).where(industry.is_not(None)).distinct()))

    def save(self, data: StoreData) -> None:
        """Одна транзакция: upsert всех кейсов и добавление новых URL; кейсы не удаляются."""
        with self._transaction() as c:
            for case in data.cases:
                dump = case.model_dump(mode="json")
                row = {"id": case.id, "level": dump["level"], "first_seen": case.first_seen,
                       "updated": case.updated, "data": dump}
                stmt = insert(cases_table).values(row)
                c.execute(stmt.on_conflict_do_update(
                    index_elements=[cases_table.c.id],
                    set_={"level": stmt.excluded.level, "first_seen": stmt.excluded.first_seen,
                          "updated": stmt.excluded.updated,
                          # При обновлении известных полей сохраняем архивные поля JSONB.
                          "data": cases_table.c.data.op("||")(stmt.excluded.data)}))
            if data.processed_urls:
                c.execute(insert(urls_table).on_conflict_do_nothing(),
                          [{"url": u} for u in sorted(data.processed_urls)])

    def updated_at(self) -> datetime | None:
        with self.engine.connect() as c:
            return c.execute(select(func.max(urls_table.c.added))).scalar()
