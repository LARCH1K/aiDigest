from datetime import date

from aidigest.db.engine import make_engine
from aidigest.models import MetricKind, Stage, StrategyLink
from aidigest.publication import case_update
from aidigest.store import PgCaseStore, StoreData
from aidigest.strategy import STRATEGY_KPIS

case_id = "demo-evraz-wheel-marking"
kpi_id = "ai-spending"

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

        link = StrategyLink(
            kpi_id=kpi_id, source_url=metric.source_url, quote=metric.quote,
            explanation="В публикации указаны фактические затраты комбината на внедрение машинного зрения.",
        )
        before = case.model_dump()
        with case_update(case, date.today()):
            if not any(row.kpi_id == kpi_id and row.source_url == link.source_url
                       for row in case.strategy_links):
                case.strategy_links.append(link)
            if case.stage == Stage.DEPLOYED:
                case.stage = Stage.PILOT
        if case.model_dump() != before:
            locked.save(StoreData(cases=[case]))

    print(f"Проверьте фильтр: {STRATEGY_KPIS[kpi_id].label}")

if __name__ == "__main__":
    engine = make_engine()
    try:
        update_case(PgCaseStore(engine))
    finally:
        engine.dispose()
