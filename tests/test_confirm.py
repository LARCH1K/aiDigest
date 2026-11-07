from datetime import date, timedelta

import pytest

from aidigest.budget import BudgetExceeded, CreditBudget
from aidigest.confirm import confirm_case, confirmation_query, plan_confirmation_queue
from aidigest.models import Article, ConfirmationStatus, Flag
from fakes import FakeLLM, FakeSearch

D = date(2026, 11, 7)
KP = Article(url="https://chel.kp.ru/1", domain="chel.kp.ru", title="",
             text="время в заторах сократилось в 2,5 раза, ДТП со 161 до 122")


def test_queue_order_and_recheck_rules(make_case, make_metric):
    m = [make_metric()]
    new = make_case(id="n", metrics=m)
    deferred = make_case(id="d", metrics=m)
    old = make_case(id="o", metrics=m, confirmation_attempts=1, last_confirmation_attempt=D - timedelta(days=30))
    fresh = make_case(id="f", metrics=m, confirmation_attempts=1, last_confirmation_attempt=D - timedelta(days=3))
    done = make_case(id="x", metrics=m, confirmation_attempts=3, last_confirmation_attempt=D - timedelta(days=90))
    nometrics = make_case(id="z", metrics=[])
    q = plan_confirmation_queue([old, deferred, new, fresh, done, nometrics], {"n"}, D, 28, 2)
    assert [c.id for c in q] == ["n", "d", "o"]


def test_confirmed_cases_are_not_rechecked(make_case, make_metric):
    c = make_case(metrics=[make_metric(confirmed_by=["https://a.ru"])], confirmation_attempts=1,
                  last_confirmation_attempt=D - timedelta(days=60))
    c.recompute_status()
    assert plan_confirmation_queue([c], set(), D, 28, 2) == []


def test_confirmation_query_skips_empty_parts(make_case):
    c = make_case(region=None, country="Германия", organization=None, ai_technology="агентный ИИ", title="Пилот")
    assert confirmation_query(c) == "Германия агентный ИИ Пилот"


def test_confirm_agrees_adds_source(make_case, make_metric, registry):
    c = make_case(metrics=[make_metric(change="-24%", quote="...")])
    llm = FakeLLM([{"matches": [{"metric_index": 0, "url": KP.url, "value": "161 → 122", "agrees": True,
                                 "quote": "ДТП со 161 до 122"}]}])
    s = FakeSearch(lambda **kw: [KP])
    confirm_case(c, s, llm, registry, D, 5)
    assert c.confirmation_status == ConfirmationStatus.CONFIRMED and c.confirmation_attempts == 1
    assert c.last_confirmation_attempt == D
    assert KP.url in c.metrics[0].confirmed_by and any(src.domain == "chel.kp.ru" for src in c.sources)
    assert s.calls[0]["pool"] == "confirm" and "gubernia74.ru" in s.calls[0]["exclude_domains"]


def test_confirm_disagrees_records_conflict(make_case, make_metric, registry):
    c = make_case(metrics=[make_metric()])
    llm = FakeLLM([{"matches": [{"metric_index": 0, "url": KP.url, "value": "в 2,5 раза", "agrees": False,
                                 "quote": "сократилось в 2,5 раза"}]}])
    confirm_case(c, FakeSearch(lambda **kw: [KP]), llm, registry, D, 5)
    assert c.confirmation_status == ConfirmationStatus.CONFLICT
    assert c.metrics[0].conflicting_values == [f"в 2,5 раза ({KP.url})"]


def test_confirm_ignores_quote_not_in_article(make_case, make_metric, registry):
    c = make_case(metrics=[make_metric()])
    llm = FakeLLM([{"matches": [{"metric_index": 0, "url": KP.url, "value": "x", "agrees": True,
                                 "quote": "выдумано"}]}])
    confirm_case(c, FakeSearch(lambda **kw: [KP]), llm, registry, D, 5)
    assert c.confirmation_status == ConfirmationStatus.SINGLE and Flag.SINGLE_SOURCE in c.flags


def test_confirm_ignores_unknown_url_and_bad_index(make_case, make_metric, registry):
    c = make_case(metrics=[make_metric()])
    llm = FakeLLM([{"matches": [
        {"metric_index": 0, "url": "https://other.ru", "value": "x", "agrees": True, "quote": "ДТП со 161 до 122"},
        {"metric_index": 7, "url": KP.url, "value": "x", "agrees": True, "quote": "ДТП со 161 до 122"}]}])
    confirm_case(c, FakeSearch(lambda **kw: [KP]), llm, registry, D, 5)
    assert c.confirmation_status == ConfirmationStatus.SINGLE


def test_no_articles_counts_attempt_without_llm(make_case, make_metric, registry):
    c = make_case(metrics=[make_metric()])
    llm = FakeLLM([])
    confirm_case(c, FakeSearch(lambda **kw: []), llm, registry, D, 5)
    assert c.confirmation_attempts == 1 and llm.calls == 0


def test_budget_exceeded_leaves_case_untouched(make_case, make_metric, registry):
    c = make_case(metrics=[make_metric()])
    s = FakeSearch(lambda **kw: [KP], budget=CreditBudget(0))
    with pytest.raises(BudgetExceeded):
        confirm_case(c, s, FakeLLM([]), registry, D, 5)
    assert c.confirmation_attempts == 0 and Flag.CONFIRMATION_SKIPPED in c.flags
