from datetime import date

import pytest

from aidigest.dedup import merge_into
from aidigest.models import Article, Level
from fakes import FakeLLM


TODAY = date(2026, 11, 16)
QUOTE = "Помощник на основе искусственного интеллекта готовит проекты ответов на обращения жителей."


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


def test_plan_keeps_only_evidenced_applicable_links(make_case, make_metric):
    from aidigest.national_plan import classify_plan

    metric = make_metric(name="проекты ответов на обращения", quote=QUOTE)
    case = make_case(metrics=[metric])
    link = {"indicator_id": "1.2", "source_url": metric.source_url, "quote": QUOTE,
            "evidence_type": "reply_drafts", "explanation": "ИИ готовит черновики ответов жителям."}
    llm = FakeLLM([{"links": [link, dict(link, indicator_id="ai-spending"), dict(link, quote="Выдумано"),
                              dict(link, indicator_id="3.2"), dict(link, source_url="https://other.example/"),
                              dict(link, source_url="https://example.org:bad/")]}])
    classify_plan(case, llm, [])
    classify_plan(case, llm, [])
    assert [item.indicator_id for item in case.plan_links] == ["1.2"]
    assert case.plan_links[0].quote == QUOTE


def test_unverified_archive_quote_cannot_be_used_without_article(make_case, make_metric):
    from aidigest.national_plan import classify_plan

    case = make_case(metrics=[make_metric(quote=QUOTE, quote_verified=False)])
    classify_plan(case, FakeLLM([]), [])
    assert case.plan_links == []
    assert case.plan_input is None


def test_all_invalid_links_leave_case_open_for_retry(make_case, make_metric):
    from aidigest.llm import LLMFormatError
    from aidigest.national_plan import classify_plan

    case = make_case(metrics=[make_metric(quote=QUOTE)])
    llm = FakeLLM([{"links": [{"indicator_id": "invented"}]}, {"links": []}])
    with pytest.raises(LLMFormatError):
        classify_plan(case, llm, [])
    assert case.plan_input is None
    classify_plan(case, llm, [])
    assert case.plan_input is not None


@pytest.mark.parametrize(("level", "region"), [(Level.WORLD, None), (Level.RF_REGIONS, "федеральный уровень")])
def test_regional_plan_excludes_overseas_and_federal_cases(make_case, make_metric, level, region):
    from aidigest.national_plan import classify_plan

    metric = make_metric(quote=QUOTE)
    case = make_case(level=level, region=region, metrics=[metric])
    classify_plan(case, FakeLLM([]), [])
    assert not case.plan_links


def test_repeated_confirmation_changes_date_only_when_evidence_changes(make_case, registry):
    from aidigest.confirm import confirm_case
    from fakes import FakeSearch

    case = make_case()
    confirm_case(case, FakeSearch({}), FakeLLM([]), registry, TODAY, 3)
    assert case.updated == date(2026, 11, 1)
    basis = "Исследователи провели собственные замеры."
    quote = "Время в пробках сократилось с 13 до 5 минут."
    article = Article(url="https://second.example/a", domain="second.example", title="Статья",
                      text=f"{basis} {quote}", published_at="2026-11-02")
    match = {"url": article.url, "metric_index": 0, "quote": quote, "agrees": True,
             "independent": True, "basis_quote": basis}
    confirm_case(case, FakeSearch(lambda **_: [article]), FakeLLM([{"matches": [match]}]), registry, TODAY, 3)
    assert case.updated == TODAY
    assert case.sources[-1].published_at == "2026-11-02"


@pytest.mark.parametrize("retry", [False, True])
def test_regular_cycle_persists_plan_link_and_backfills_repeat_publication(registry, case_reply, case_store, retry):
    from aidigest.budget import CreditBudget
    from aidigest.config import QuerySpec, Settings
    from aidigest.extract import SYSTEM_PROMPT
    from aidigest.pipeline import Deps, run_cycle
    from fakes import FakeSearch

    article = Article(url="https://gubernia74.ru/news/1", domain="gubernia74.ru", title="Статья",
                      text=f"{QUOTE} В Челябинской области ИИ анализирует дорожную обстановку. "
                           "Время в пробках сократилось с 13 до 5 минут.")
    links = {"links": [{"indicator_id": "1.2", "source_url": article.url, "quote": QUOTE,
                        "evidence_type": "reply_drafts", "explanation": "ИИ готовит черновики ответов жителям."}]}
    query = QuerySpec(level=Level.RF_REGIONS, text="Кейсы", use_registry_domains=False, language="ru")
    day = date(2026, 11, 15)

    def run(material, today, plan_reply):
        budget = CreditBudget(20)
        search = FakeSearch(lambda **kw: [material] if kw["pool"] == "collect" else [], budget=budget)
        llm = FakeLLM(lambda system, _: case_reply() if system == SYSTEM_PROMPT else plan_reply)
        return run_cycle(Deps(search, llm, registry, case_store, [query], Settings(), budget), {query.level}, today)

    assert run(article, day, {"invalid": []} if retry else links).cases_new == 1
    assert bool(case_store.load().cases[0].plan_links) is not retry
    article.published_at = "2026-11-04"
    assert run(article, TODAY, links).cases_updated == 1
    case = case_store.load().cases[0]
    assert case.plan_links[0].indicator_id == "1.2"
    assert case.updated == TODAY and case.sources[0].published_at == "2026-11-04"
