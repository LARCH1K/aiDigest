from datetime import date

import pytest

from aidigest.confirm import confirm_case
from aidigest.dedup import find_duplicate, merge_into
from aidigest.models import Article, ConfirmationStatus, PlanLink
from aidigest.national_plan import classify_plan
from fakes import FakeLLM, FakeSearch


@pytest.mark.parametrize(("indicator", "evidence_type", "quote"), [
    ("1.2", "reply_drafts", "Губернатор сообщил, что ИИ адаптирует работу городских светофоров."),
    ("3.3", "daily_document_use", "С помощью ИИ-сервиса «ГосПромпт» за год подготовили 27 тысяч документов."),
    ("3.2", "document_index", "ИИ помог проверить 687 актов исполнительной документации."),
    ("2.3", "all_incoming_calls", "ИИ обрабатывает все входящие данные системы видеонаблюдения."),
])
def test_literal_but_irrelevant_plan_quote_does_not_create_link(make_case, make_source, indicator, evidence_type, quote):
    url = "https://example.org/news"
    case = make_case(metrics=[], sources=[make_source(url)])
    article = Article(url=url, domain="example.org", title="Новости", text=quote)
    llm = FakeLLM([{"links": [{"indicator_id": indicator, "evidence_type": evidence_type,
                              "source_url": url, "quote": quote, "explanation": "ИИ применяют в процессе."}]}])

    classify_plan(case, llm, [article])

    assert case.plan_links == []


def test_reclassification_replaces_old_links_for_covered_source(make_case, make_source):
    url = "https://example.org/news"
    case = make_case(metrics=[], sources=[make_source(url)], plan_links=[
        PlanLink(indicator_id="1.2", source_url=url, quote="старая цитата", explanation="старая связь")])
    article = Article(url=url, domain="example.org", title="Транспорт", text="ИИ управляет светофорами города.")

    classify_plan(case, FakeLLM([{"links": []}]), [article])

    assert case.plan_links == []


def test_same_region_does_not_merge_transport_and_medical_projects(make_case):
    common = {"region": "Пензенская область", "organization": "Правительство Пензенской области"}
    transport = make_case(id="transport", industry="транспорт", title="Адаптивные светофоры", **common)
    medicine = make_case(id="health", industry="здравоохранение", title="Анализ электронных медкарт", **common)

    assert find_duplicate(medicine, [transport], FakeLLM([{"duplicate_id": "transport"}])) is None


def test_identical_numbers_on_two_domains_do_not_confirm_during_merge(make_case, make_metric, make_source):
    first = make_case(metrics=[make_metric()], sources=[make_source()])
    url = "https://another.example/news"
    second = make_case(metrics=[make_metric(source_url=url)], sources=[make_source(url)])

    merge_into(first, second, date(2026, 11, 27))

    assert [source.url for source in first.sources] == [first.metrics[0].source_url, url]
    assert first.metrics[0].confirmed_by == []
    assert first.confirmation_status == ConfirmationStatus.SINGLE


def test_repeated_governor_statement_is_not_independent_evidence(make_case, make_metric, registry):
    metric = make_metric(name="доля жителей", before=None, after="34%", change=None,
                         quote="По словам губернатора, у 34% жителей выявлены факторы риска.")
    case = make_case(region="Пензенская область", metrics=[metric])
    text = "На прямой линии губернатор Пензенской области сообщил, что у 34% жителей выявлены факторы риска."
    article = Article(url="https://second.example/interview", domain="second.example", title="Прямая линия", text=text)
    llm = FakeLLM([{"matches": [{"metric_index": 0, "url": article.url, "agrees": True, "quote": text,
                                 "basis_quote": text, "independent": True}]}])

    confirm_case(case, FakeSearch(lambda **_: [article]), llm, registry, date(2026, 11, 27), 5)

    assert metric.confirmed_by == []
    assert case.confirmation_status == ConfirmationStatus.SINGLE


def test_independent_measurement_keeps_the_cited_evidence(make_case, make_metric, registry):
    case = make_case(metrics=[make_metric()])
    basis = "Исследователи университета самостоятельно измерили время на перекрёстке."
    quote = "По данным замеров время в пробках сократилось с 13 до 5 минут."
    article = Article(url="https://university.example/study", domain="university.example", title="Замеры",
                      text=f"{basis} {quote}")
    llm = FakeLLM([{"matches": [{"metric_index": 0, "url": article.url, "agrees": True, "quote": quote,
                                 "basis_quote": basis, "independent": True}]}])

    confirm_case(case, FakeSearch(lambda **_: [article]), llm, registry, date(2026, 11, 27), 5)

    assert case.confirmation_status == ConfirmationStatus.CONFIRMED
    evidence = case.metrics[0].confirmation_evidence[0]
    assert (evidence.source_url, evidence.quote, evidence.basis_quote) == (article.url, quote, basis)


def test_regular_collection_does_not_extract_an_old_article(registry, case_store):
    from aidigest.budget import CreditBudget
    from aidigest.config import QuerySpec, Settings
    from aidigest.models import Level
    from aidigest.pipeline import Deps, run_cycle

    old = Article(url="https://example.org/2024/02/36414", domain="example.org", title="Формы госуслуг",
                  text="Министерство представило интерактивные формы заявлений.")
    budget = CreditBudget(10)
    llm = FakeLLM([{"cases": []}])
    query = QuerySpec(level=Level.SVERDLOVSK, text="Госуслуги", use_registry_domains=False)
    deps = Deps(FakeSearch(lambda **_: [old], budget=budget), llm, registry, case_store, [query], Settings(), budget)

    report = run_cycle(deps, {Level.SVERDLOVSK}, date(2026, 11, 27))

    assert (report.articles_processed, report.as_rows()["Статей вне окна свежести"], llm.calls) == (0, 1, 0)
    assert old.url not in case_store.load().processed_urls
