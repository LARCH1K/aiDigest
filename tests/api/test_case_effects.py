from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aidigest.models import Case, Level
from aidigest.services.cases import CaseService
from aidigest.services.catalog import CatalogService
from aidigest.store import MemoryStore, StoreData
from aidigest_api.routes import api_routes

KPI_ID = "workforce-skills"
LINK = {
    "kpi_id": KPI_ID,
    "explanation": "Проект обучает сотрудников работе с ИИ.",
    "source_url": "https://gubernia74.ru/news/1",
    "quote": "сотрудники освоили работу с ИИ",
}


@pytest.fixture
def effects_client(make_case, make_metric):
    matching = make_case(id="matching", updated=date(2026, 11, 4), metrics=[
        make_metric(criterion="скорость"),
        make_metric(criterion="скорость"),
        make_metric(criterion="скорость"),
        make_metric(name="доля ошибок", criterion="качество", quote_verified=False),
    ])
    without_metrics = make_case(id="only_kpi", metrics=[])
    without_kpi = make_case(id="only_criterion", level=Level.SVERDLOVSK,
                            metrics=[make_metric(criterion="качество")])
    data = StoreData(cases=[
        Case.model_validate({**matching.model_dump(), "strategy_links": [LINK], "strategy_input": "fingerprint"}),
        Case.model_validate({**without_metrics.model_dump(), "strategy_links": [LINK]}),
        without_kpi,
    ])
    app = FastAPI()
    app.include_router(api_routes(CaseService(MemoryStore(data)), CatalogService(Path("config")), SimpleNamespace()))
    return TestClient(app)


def test_meta_exposes_effect_and_strategy_options(effects_client):
    meta = effects_client.get("/api/meta").json()
    assert {"value": "скорость", "label": "Скорость"} in meta["criteria"]
    assert {"value": "ROI", "label": "ROI"} in meta["criteria"]
    option = next(option for option in meta["strategy_kpis"] if option["value"] == KPI_ID)
    assert option["label"] and option["clause"] and option["url"].startswith("https://")


def test_list_and_detail_expose_all_metrics_and_kpi_evidence(effects_client):
    case = next(row for row in effects_client.get("/api/cases").json()["cases"] if row["id"] == "matching")
    detail = effects_client.get("/api/cases/matching").json()
    assert case["updated"] == detail["updated"] == "2026-11-04"
    assert case["first_seen"] == "2026-11-01"
    assert case["headline"] == "время в пробках: 13 мин → 5 мин"
    assert case["headline_unverified"] is False
    assert case["metrics"] == detail["metrics"]
    assert len(case["metrics"]) == 4
    assert case["metrics"][3]["name"] == "доля ошибок"
    assert case["metrics"][3]["quote_verified"] is False
    assert case["strategy_links"] == detail["strategy_links"] == [LINK]
    assert "strategy_input" not in detail
    schemas = effects_client.get("/openapi.json").json()["components"]["schemas"]
    assert "strategy_input" not in schemas["CaseDetail"]["properties"]


@pytest.mark.parametrize(("params", "expected"), [
    ({}, {"matching", "only_criterion"}),
    ({"criterion": "скорость"}, {"matching"}),
    ({"criterion": "качество"}, {"matching", "only_criterion"}),
    ({"criterion": "качество", "level": "Свердловская область"}, {"only_criterion"}),
    ({"criterion": "качество", "kpi": KPI_ID}, {"matching"}),
    ({"criterion": "качество", "kpi": KPI_ID, "level": "Свердловская область"}, set()),
    ({"kpi": KPI_ID}, {"matching", "only_kpi"}),
    ({"kpi": KPI_ID, "metrics": "0"}, {"matching", "only_kpi"}),
    ({"kpi": KPI_ID, "metrics": "1"}, {"matching"}),
])
def test_effect_filters_combine_with_each_other_and_existing_filters(effects_client, params, expected):
    response = effects_client.get("/api/cases", params=params)
    assert response.status_code == 200
    assert {row["id"] for row in response.json()["cases"]} == expected


@pytest.mark.parametrize("params", [{"criterion": "неизвестный"}, {"kpi": "unknown"}])
def test_unknown_effect_filters_are_rejected(effects_client, params):
    response = effects_client.get("/api/cases", params=params)
    assert response.status_code == 422
