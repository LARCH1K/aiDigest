"""База кейсов: протокол Store, реализация в памяти (тесты) и в Postgres."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine

from aidigest.db.schema import cases as cases_table
from aidigest.db.schema import processed_urls as urls_table
from aidigest.models import Case


@dataclass
class StoreData:
    cases: list[Case] = field(default_factory=list)
    processed_urls: set[str] = field(default_factory=set)


class Store(Protocol):
    def load(self) -> StoreData: ...

    def save(self, data: StoreData) -> None: ...


class MemoryStore:
    """Хранит глубокую копию, чтобы тесты ловили «забыли save»."""

    def __init__(self, data: StoreData | None = None):
        self._data = self._copy(data or StoreData())

    @staticmethod
    def _copy(data: StoreData) -> StoreData:
        return StoreData([c.model_copy(deep=True) for c in data.cases], set(data.processed_urls))

    def load(self) -> StoreData:
        return self._copy(self._data)

    def save(self, data: StoreData) -> None:
        self._data = self._copy(data)


class PgCaseStore:
    def __init__(self, engine: Engine):
        self.engine = engine

    def load(self) -> StoreData:
        with self.engine.connect() as c:
            rows = c.execute(select(cases_table.c.data).order_by(cases_table.c.first_seen, cases_table.c.id))
            cases = [Case.model_validate(r[0]) for r in rows]
            urls = {r[0] for r in c.execute(select(urls_table.c.url))}
        return StoreData(cases, urls)

    def save(self, data: StoreData) -> None:
        """Одна транзакция: upsert всех кейсов и добавление новых URL; кейсы не удаляются."""
        with self.engine.begin() as c:
            for case in data.cases:
                dump = case.model_dump(mode="json")
                row = {"id": case.id, "level": dump["level"], "first_seen": case.first_seen,
                       "updated": case.updated, "data": dump}
                stmt = insert(cases_table).values(row)
                c.execute(stmt.on_conflict_do_update(
                    index_elements=[cases_table.c.id],
                    set_={k: stmt.excluded[k] for k in ("level", "first_seen", "updated", "data")}))
            if data.processed_urls:
                c.execute(insert(urls_table).on_conflict_do_nothing(),
                          [{"url": u} for u in sorted(data.processed_urls)])

    def updated_at(self) -> datetime | None:
        with self.engine.connect() as c:
            return c.execute(select(func.max(urls_table.c.added))).scalar()
