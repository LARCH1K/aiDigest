import pytest
from sqlalchemy import inspect, select

from aidigest.db.schema import cases, metadata
from aidigest.store import PgCaseStore, StoreData

pytestmark = pytest.mark.pg


def test_roundtrip_and_upsert(pg, make_case):
    s = PgCaseStore(pg)
    s.save(StoreData([make_case(id="c1", title="А")], {"https://x.ru/1"}))
    d = s.load()
    d.cases[0].title = "Б"
    d.cases.append(make_case(id="c2"))
    s.save(d)
    again = s.load()
    assert {c.id: c.title for c in again.cases} == {"c1": "Б", "c2": "Умные светофоры"}
    assert again.processed_urls == {"https://x.ru/1"}
    assert s.updated_at() is not None


def test_empty_db_loads_empty(pg):
    assert PgCaseStore(pg).load() == StoreData() and PgCaseStore(pg).updated_at() is None


def test_archive_update_preserves_legacy_evidence_without_exposing_it_as_plan(pg, make_case):
    case = make_case(industry="ЖКХ")
    legacy_links = [{"kpi_id": "ai-spending", "quote": "Проект требует инвестиций."}]
    data = case.model_dump(mode="json", exclude={"plan_links", "plan_input"})
    data["strategy_links"] = legacy_links
    with pg.begin() as conn:
        conn.execute(cases.insert().values(id=case.id, level=case.level, first_seen=case.first_seen,
                                           updated=case.updated, data=data))
    store = PgCaseStore(pg)
    saved, = store.load().cases
    assert saved.plan_links == []
    assert store.industry_names() == {"ЖКХ"}
    saved.industry = "Транспорт"
    store.save(StoreData([saved]))
    assert store.industry_names() == {"Транспорт"}
    with pg.begin() as conn:
        updated = conn.scalar(select(cases.c.data).where(cases.c.id == case.id))
    assert updated["strategy_links"] == legacy_links
    assert updated["plan_links"] == []


def test_save_is_atomic(pg, make_case):
    bad = make_case(id="c2")
    object.__setattr__(bad, "level", None)   # сломает INSERT
    with pytest.raises(Exception):
        PgCaseStore(pg).save(StoreData([make_case(id="c1"), bad], {"https://x.ru/1"}))
    assert PgCaseStore(pg).load() == StoreData()


def test_save_does_not_delete_cases(pg, make_case):
    s = PgCaseStore(pg)
    s.save(StoreData([make_case(id="c1"), make_case(id="c2")], set()))
    s.save(StoreData([make_case(id="c1")], set()))
    assert {c.id for c in s.load().cases} == {"c1", "c2"}


def test_writer_lock_excludes_another_connection_and_is_released_after_error(pg, make_case):
    from aidigest.store import WriterBusy

    first = PgCaseStore(pg)
    second = PgCaseStore(pg)
    with pytest.raises(ValueError, match="прервано"):
        with first.write_lock() as writer:
            writer.save(StoreData([make_case(id="c1")]))
            assert second.load().cases[0].id == "c1"
            with pytest.raises(WriterBusy), second.write_lock():
                pytest.fail("Два процесса одновременно захватили блокировку записи")
            raise ValueError("прервано")
    with second.write_lock() as writer:
        assert writer.load().cases[0].id == "c1"


def test_schema_py_matches_migrated_db(pg):
    """schema.py и миграции не должны расходиться по колонкам."""
    insp = inspect(pg)
    for name, table in metadata.tables.items():
        db_cols = {c["name"]: c for c in insp.get_columns(name)}
        assert set(db_cols) == {c.name for c in table.columns}, name
        for col in table.columns:
            assert db_cols[col.name]["nullable"] == col.nullable or col.primary_key, (name, col.name)
