from datetime import date

import pytest

from aidigest.dedup import merge_into
from aidigest.models import Article, Level
from fakes import FakeLLM


TODAY = date(2026, 11, 16)
QUOTE = "Сотрудники освоили навыки работы с инструментами искусственного интеллекта."


@pytest.mark.parametrize(("metadata", "body", "expected"), [
    ("2026-11-02T22:10:00+05:00", "", "2026-11-02"),
    ("Mon, 02 Nov 2026 11:00:00 GMT", "", "2026-11-02"),
    (None, "Опубликовано: 2 ноября 2026 года. Обновлено: 7 ноября 2026 года.", "2026-11-02"),
    (None, "Мероприятие прошло 2 ноября 2026 года.", None),
    ("2026-02-30", "Дата обновления: 2026-11-02", None),
])
def test_source_uses_only_a_valid_publication_date(registry, metadata, body, expected):
    article = Article(url="https://example.org/a", domain="example.org", title="Статья",
                      text=body, published_at=metadata)
    assert registry.to_source(article).published_at == expected


def test_duplicate_update_depends_on_new_visible_data(make_case, make_source):
    case = make_case()
    merge_into(case, make_case(), TODAY)
    assert case.updated == date(2026, 11, 1)
    merge_into(case, make_case(sources=[make_source(published_at="2026-11-02")]), TODAY)
    assert case.updated == TODAY
    assert len(case.sources) == 1 and case.sources[0].published_at == "2026-11-02"


def test_catalog_covers_all_official_clauses():
    from aidigest.strategy import STRATEGY_KPIS

    assert {kpi.clause for kpi in STRATEGY_KPIS.values()} == {
        f"28.1.{letter}" for letter in "абвгдежзик"
    }


def test_strategy_keeps_only_evidenced_applicable_links(make_case, make_metric):
    from aidigest.strategy import classify_strategy

    metric = make_metric(name="число обученных сотрудников", quote=QUOTE)
    case = make_case(metrics=[metric])
    link = {"kpi_id": "workforce-skills", "source_url": metric.source_url, "quote": QUOTE,
            "evidence_type": "training", "explanation": "Работники освоили инструменты ИИ."}
    llm = FakeLLM([{"links": [link, dict(link, kpi_id="invented"), dict(link, quote="Выдумано"),
                              dict(link, kpi_id="gdp-growth"), dict(link, source_url="https://other.example/"),
                              dict(link, source_url="https://example.org:bad/")]}])
    classify_strategy(case, llm, [])
    classify_strategy(case, llm, [])
    assert [item.kpi_id for item in case.strategy_links] == ["workforce-skills"]
    assert case.strategy_links[0].quote == QUOTE


def test_unverified_archive_quote_cannot_be_used_without_article(make_case, make_metric):
    from aidigest.strategy import classify_strategy

    case = make_case(metrics=[make_metric(quote=QUOTE, quote_verified=False)])
    classify_strategy(case, FakeLLM([]), [])
    assert case.strategy_links == []
    assert case.strategy_input is None


def test_all_invalid_links_leave_case_open_for_retry(make_case, make_metric):
    from aidigest.llm import LLMFormatError
    from aidigest.strategy import classify_strategy

    case = make_case(metrics=[make_metric(quote=QUOTE)])
    llm = FakeLLM([{"links": [{"kpi_id": "invented"}]}, {"links": []}])
    with pytest.raises(LLMFormatError):
        classify_strategy(case, llm, [])
    assert case.strategy_input is None
    classify_strategy(case, llm, [])
    assert case.strategy_input is not None


def test_russian_workforce_kpi_excludes_overseas_case(make_case, make_metric):
    from aidigest.strategy import classify_strategy

    metric = make_metric(quote=QUOTE)
    case = make_case(level=Level.WORLD, country="Япония", region=None, metrics=[metric])
    classify_strategy(case, FakeLLM([]), [])
    assert not case.strategy_links


def test_repeated_confirmation_changes_date_only_when_evidence_changes(make_case, registry):
    from aidigest.confirm import confirm_case
    from fakes import FakeSearch

    case = make_case()
    confirm_case(case, FakeSearch({}), FakeLLM([]), registry, TODAY, 3)
    assert case.updated == date(2026, 11, 1)
    article = Article(url="https://second.example/a", domain="second.example", title="Статья",
                      text="Время в пробках сократилось с 13 до 5 минут.", published_at="2026-11-02")
    match = {"url": article.url, "metric_index": 0, "quote": article.text, "agrees": True}
    confirm_case(case, FakeSearch(lambda **_: [article]), FakeLLM([{"matches": [match]}]), registry, TODAY, 3)
    assert case.updated == TODAY
    assert case.sources[-1].published_at == "2026-11-02"


@pytest.mark.parametrize("retry", [False, True])
def test_regular_cycle_persists_kpi_and_backfills_repeat_publication(registry, case_reply, case_store, retry):
    from aidigest.budget import CreditBudget
    from aidigest.config import QuerySpec, Settings
    from aidigest.extract import SYSTEM_PROMPT
    from aidigest.pipeline import Deps, run_cycle
    from fakes import FakeSearch

    article = Article(url="https://gubernia74.ru/news/1", domain="gubernia74.ru", title="Статья",
                      text=f"{QUOTE} Время в пробках сократилось с 13 до 5 минут.")
    links = {"links": [{"kpi_id": "workforce-skills", "source_url": article.url, "quote": QUOTE,
                        "evidence_type": "training", "explanation": "Сотрудники освоили инструменты ИИ."}]}
    query = QuerySpec(level=Level.RF_REGIONS, text="Кейсы", use_registry_domains=False, language="ru")
    day = date(2026, 11, 15)

    def run(material, today, strategy_reply):
        budget = CreditBudget(20)
        search = FakeSearch(lambda **kw: [material] if kw["pool"] == "collect" else [], budget=budget)
        llm = FakeLLM(lambda system, _: case_reply() if system == SYSTEM_PROMPT else strategy_reply)
        return run_cycle(Deps(search, llm, registry, case_store, [query], Settings(), budget), {query.level}, today)

    assert run(article, day, {"invalid": []} if retry else links).cases_new == 1
    assert bool(case_store.load().cases[0].strategy_links) is not retry
    article.published_at = "2026-11-04"
    assert run(article, TODAY, links).cases_updated == 1
    case = case_store.load().cases[0]
    assert case.strategy_links[0].kpi_id == "workforce-skills"
    assert case.updated == TODAY and case.sources[0].published_at == "2026-11-04"
