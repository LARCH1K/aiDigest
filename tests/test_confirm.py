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
    c = make_case(metrics=[make_metric(name="ДТП", before="161", after="122", quote="...")])
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


# --- финальное ревью ---

def test_agreement_quote_must_contain_metric_numbers(make_case, make_metric, registry):
    art = Article(url="https://chel.kp.ru/2", domain="chel.kp.ru", title="", text="Погода в Челябинске была хорошей.")
    c = make_case(metrics=[make_metric()])
    llm = FakeLLM([{"matches": [{"metric_index": 0, "url": art.url, "value": "13 → 5", "agrees": True,
                                 "quote": "Погода в Челябинске"}]}])
    confirm_case(c, FakeSearch(lambda **kw: [art]), llm, registry, D, 5)
    assert c.confirmation_status == ConfirmationStatus.SINGLE and c.metrics[0].confirmed_by == []


def test_disagreement_value_must_be_in_quote(make_case, make_metric, registry):
    c = make_case(metrics=[make_metric()])
    llm = FakeLLM([{"matches": [{"metric_index": 0, "url": KP.url, "value": "40 минут", "agrees": False,
                                 "quote": "ДТП со 161 до 122"}]}])
    confirm_case(c, FakeSearch(lambda **kw: [KP]), llm, registry, D, 5)
    assert c.confirmation_status == ConfirmationStatus.SINGLE


def test_unverified_metric_cannot_be_confirmed(make_case, make_metric, registry):
    c = make_case(metrics=[make_metric(before="161", after="122", quote_verified=False)])
    llm = FakeLLM([{"matches": [{"metric_index": 0, "url": KP.url, "value": "161 → 122", "agrees": True,
                                 "quote": "ДТП со 161 до 122"}]}])
    confirm_case(c, FakeSearch(lambda **kw: [KP]), llm, registry, D, 5)
    assert c.metrics[0].confirmed_by == []


def test_articles_from_case_domains_are_dropped(make_case, make_metric, registry):
    same = Article(url="https://www.gubernia74.ru/a", domain="gubernia74.ru", title="",
                   text="сократилось с 13 до 5 минут")
    c = make_case(metrics=[make_metric()])
    llm = FakeLLM([])
    confirm_case(c, FakeSearch(lambda **kw: [same]), llm, registry, D, 5)
    assert llm.calls == 0 and c.confirmation_status == ConfirmationStatus.SINGLE and len(c.sources) == 1


def test_recheck_searches_only_since_last_attempt(make_case, make_metric, registry):
    last = D - timedelta(days=30)
    c = make_case(metrics=[make_metric()], confirmation_attempts=1, last_confirmation_attempt=last)
    s = FakeSearch(lambda **kw: [])
    confirm_case(c, s, FakeLLM([]), registry, D, 5)
    assert s.calls[0]["start_date"] == last
    first = make_case(metrics=[make_metric()])
    s2 = FakeSearch(lambda **kw: [])
    confirm_case(first, s2, FakeLLM([]), registry, D, 5)
    assert s2.calls[0]["start_date"] is None


# --- детерминированное подтверждение по числам ---
from aidigest.confirm import find_number_confirmations

CHEL = Article(url="https://74.ru/news/1", domain="74.ru", title="",
               text="В Челябинске заработала система. Среднее время в пробках сократилось с 13 до 5 минут, сообщили в мэрии.")


def test_code_confirms_when_numbers_name_and_place_match(make_case, make_metric, registry):
    c = make_case(region="Челябинская область", metrics=[make_metric(name="время в пробках", before="13 мин", after="5 мин")])
    found = find_number_confirmations(c, [CHEL])
    assert found == [(0, "https://74.ru/news/1", "Среднее время в пробках сократилось с 13 до 5 минут, сообщили в мэрии.")]
    confirm_case(c, FakeSearch(lambda **kw: [CHEL]), FakeLLM([{"matches": []}]), registry, D, 5)
    assert c.confirmation_status == ConfirmationStatus.CONFIRMED and "https://74.ru/news/1" in c.metrics[0].confirmed_by


def test_code_does_not_confirm_without_place(make_case, make_metric):
    c = make_case(region="Белгородская область", organization="Белводоканал",
                  metrics=[make_metric(name="время в пробках", before="13 мин", after="5 мин")])
    assert find_number_confirmations(c, [CHEL]) == []


def test_code_does_not_confirm_small_numbers_only(make_case, make_metric):
    art = Article(url="https://74.ru/2", domain="74.ru", title="", text="В Челябинске время в пробках выросло с 5 до 7 минут.")
    c = make_case(region="Челябинская область", metrics=[make_metric(name="время в пробках", before="5 мин", after="7 мин",
                                                                      quote="время в пробках выросло с 5 до 7 минут")])
    assert find_number_confirmations(c, [art]) == []


def test_code_does_not_confirm_without_metric_word(make_case, make_metric):
    art = Article(url="https://74.ru/3", domain="74.ru", title="", text="В Челябинске открыли 13 школ и 5 детсадов.")
    c = make_case(region="Челябинская область", metrics=[make_metric(name="время в пробках", before="13 мин", after="5 мин")])
    assert find_number_confirmations(c, [art]) == []


def test_unverified_metric_is_not_code_confirmed(make_case, make_metric):
    c = make_case(region="Челябинская область",
                  metrics=[make_metric(name="время в пробках", before="13 мин", after="5 мин", quote_verified=False)])
    assert find_number_confirmations(c, [CHEL]) == []


def test_code_confirmation_survives_broken_llm_reply(make_case, make_metric, registry):
    from aidigest.llm import LLMFormatError

    class Broken:
        calls = 0

        def complete_json(self, system, user, validate=None):
            raise LLMFormatError("битый JSON")
    c = make_case(region="Челябинская область", metrics=[make_metric(name="время в пробках", before="13 мин", after="5 мин")])
    confirm_case(c, FakeSearch(lambda **kw: [CHEL]), Broken(), registry, D, 5)
    assert c.confirmation_status == ConfirmationStatus.CONFIRMED


def test_generic_org_words_are_not_a_place(make_case, make_metric):
    art = Article(url="https://tadviser.ru/x", domain="tadviser.ru", title="",
                  text="Обзор информационных систем. Производительность хозяйства растёт на 30% при внедрении ИИ.")
    c = make_case(region="федеральный уровень", organization="Республиканский информационно-вычислительный центр (РИВЦ)",
                  metrics=[make_metric(name="производительность хозяйства", before=None, after=None, change="+30%",
                                       quote="производительность хозяйства вырастает на 30%")])
    assert find_number_confirmations(c, [art]) == []


def test_proper_name_in_org_is_a_place(make_case, make_metric):
    art = Article(url="https://jaycopilot.com/sova", domain="jaycopilot.com", title="",
                  text="В Совкомбанке бот «Сова» экономит сотрудникам 310 000 часов в год.")
    c = make_case(region="федеральный уровень", organization="Совкомбанк",
                  metrics=[make_metric(name="экономия рабочего времени", before=None, after="310 000 часов в год",
                                       change=None, quote="экономия рабочего времени составила 310 000 часов в год")])
    assert find_number_confirmations(c, [art]) == [(0, "https://jaycopilot.com/sova",
                                                    "В Совкомбанке бот «Сова» экономит сотрудникам 310 000 часов в год.")]


def test_conflict_needs_same_unit(make_case, make_metric, registry):
    art = Article(url="https://terratech.ru/1", domain="terratech.ru", title="",
                  text="Геоаналитику «Цифровой Земли» уже используют 74 региона России.")
    c = make_case(metrics=[make_metric(name="автоматизация", before=None, after="70%", change="+70 п.п.",
                                       quote="автоматизация достигла 70%")])
    llm = FakeLLM([{"matches": [{"metric_index": 0, "url": art.url, "value": "74 региона", "agrees": False,
                                 "quote": "уже используют 74 региона России"}]}])
    confirm_case(c, FakeSearch(lambda **kw: [art]), llm, registry, D, 5)
    assert c.confirmation_status == ConfirmationStatus.SINGLE
