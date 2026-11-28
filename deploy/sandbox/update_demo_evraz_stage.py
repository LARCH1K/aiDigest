from datetime import date

from aidigest.db.engine import make_engine
from aidigest.models import MetricKind, Stage
from aidigest.publication import case_update
from aidigest.store import PgCaseStore, StoreData

case_id = "demo-evraz-wheel-marking"

def update_case(store):
    with store.write_lock() as locked:
        case = next((row for row in locked.load().cases if row.id == case_id), None)
        if case is None:
            raise SystemExit("Кейс ЕВРАЗ НТМК отсутствует. Сначала загрузите вторую подборку.")

        metric = next(
            (row for row in case.metrics
             if row.name == "Инвестиции в проект, руб."
             and row.kind == MetricKind.FACT and row.quote_verified
             and any(source.url == row.source_url for source in case.sources)),
            None,
        )
        if metric is None:
            raise SystemExit("Не найдена проверенная цитата об инвестициях в проект.")

        if case.stage == Stage.DEPLOYED:
            with case_update(case, date.today()):
                case.stage = Stage.PILOT
            locked.save(StoreData(cases=[case]))

    print(f"Стадия кейса ЕВРАЗ НТМК: {case.stage}")

if __name__ == "__main__":
    engine = make_engine()
    try:
        update_case(PgCaseStore(engine))
    finally:
        engine.dispose()
