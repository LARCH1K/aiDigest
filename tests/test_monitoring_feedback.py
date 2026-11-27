from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from aidigest.extract import extract_cases
from aidigest.methodology import m1_profile, r1_ratio
from aidigest.models import Article, Case, Level, Methodology, MetricKind
from aidigest.registry import SourceRegistry
from aidigest.services.cases import CaseService
from aidigest.services.catalog import CatalogService
from aidigest.store import MemoryStore, StoreData
from aidigest_api.routes import api_routes
from fakes import FakeLLM


def _meta(*cases):
    router = api_routes(CaseService(MemoryStore(StoreData(list(cases)))), CatalogService(Path("config")),
                        SimpleNamespace())
    handler = next(route.endpoint for route in router.routes if route.path == "/api/meta")
    return handler().model_dump()


def test_meta_exposes_six_national_plan_goals():
    indicators = _meta().get("plan_indicators", [])
    assert {item["value"]: item["target_percent"] for item in indicators} == {
        "1.1": 70, "1.2": 50, "2.3": 60, "3.1": 70, "3.2": 100, "3.3": 50,
    }


def test_meta_combines_industry_spelling_variants(make_case):
    cases = [make_case(industry=" ЖКХ "), make_case(industry="жкх"), make_case(industry="")]
    assert _meta(*cases).get("industries") == [{"value": "жкх", "label": "ЖКХ"}]


def test_world_case_retains_cited_qualitative_risk(registry, case_reply):
    quote = "Caseworkers must check every suggested decision before sending it."
    article = Article(url="https://example.org/project", domain="example.org", title="Project", text=quote)
    reply = case_reply(country="Канада", region=None)["cases"][0]
    reply["metrics"] = []
    reply["qualitative_evidence"] = [
        {"criterion": "сопутствующие риски", "fact": "Требуется проверка сотрудником.", "quote": quote},
        {"criterion": "качество и надёжность", "fact": "Есть ошибки.", "quote": "Inaccurate decisions."},
    ]
    case, = extract_cases(article, FakeLLM([{"cases": [reply]}]), registry, date(2026, 11, 27), 12_000)
    assert case.level == Level.WORLD and case.methodology == Methodology.M1
    assert case.model_dump().get("qualitative_evidence") == [{
        "criterion": "сопутствующие риски", "fact": "Требуется проверка сотрудником.",
        "source_url": article.url, "quote": quote,
    }]
    profile = m1_profile(case)
    assert list(profile) == ["результат услуги", "качество и надёжность", "производительность и труд",
                             "реализуемость и масштаб", "сопутствующие риски"]
    assert profile["качество и надёжность"] == []


@pytest.mark.parametrize(("values", "expected"), [
    ({"before": "1 200,0 мин", "after": "30 минут", "quote": "Время сократилось с 1 200,0 до 30 минут."}, 40),
    ({"before": "70 процентов", "after": "80%", "unit": "%", "quote": "Доля выросла с 70 до 80%."}, 0.875),
    ({"before": "5 мин", "after": "13 мин"}, None),
    ({"quote": "Теперь 5 минут, ранее 13 минут."}, 2.6),
    ({"quote": "Время сократилось с 13 до 5 секунд."}, None),
    ({"before": "5 мин", "after": "30 сек"}, None),
    ({"before": "5 мин", "after": "0 мин"}, None),
    ({"before": "до 13 мин"}, None),
    ({"quote_verified": False}, None),
    ({"kind": MetricKind.PLAN}, None),
    ({"conflicting_values": ["6 мин"]}, None),
])
def test_regional_ratio_requires_verified_comparable_actual_values(make_metric, values, expected):
    assert r1_ratio(make_metric(**values)) == expected


def test_m1_profile_reuses_archived_accessibility_evidence(make_case, make_metric):
    metric = make_metric(name="Доступность консультаций", criterion="опыт и доступность")
    case = make_case(level=Level.WORLD, methodology=Methodology.M1, metrics=[metric])
    assert [item.fact for item in m1_profile(case)["результат услуги"]] == [metric.name]


def test_legacy_strategy_fields_do_not_create_plan_links(make_case):
    row = make_case().model_dump(exclude={"plan_links", "plan_input"})
    row["strategy_links"] = [{"kpi_id": "ai-spending", "quote": "Проект требует инвестиций."}]
    row["strategy_input"] = "legacy"
    case = Case.model_validate(row)
    assert case.plan_links == [] and case.plan_input is None


def test_world_catalog_has_team_sources():
    registry = SourceRegistry.load(Path("config/sources.yaml"))
    assert {"kratid.ee", "algoritmes.overheid.nl", "indiaai.gov.in", "microsoft.com"} <= set(
        registry.domains_for(Level.WORLD))
    canada = registry.lookup("https://open.canada.ca/data/dataset/fcbc0200-79ba-4fa4-94a6-00e32facea6b")
    assert canada is not None and canada.reliability == "высокая"
