from datetime import date

import pytest

from aidigest.extract import extract_cases
from aidigest.llm import LLMFormatError
from aidigest.methodology import CRITERIA, OTHER_CRITERION, infer_level, methodology_prompt, select_methodology
from aidigest.models import Article, Flag, Level, Methodology, Sector, Stage
from fakes import FakeLLM

D = date(2026, 11, 7)
ART = Article(url="https://gubernia74.ru/news/1?utm_source=x", domain="gubernia74.ru", title="Пробки",
              text="В Челябинской области ИИ анализирует дорожную обстановку. "
                   "Время в пробках сократилось с 13 до 5 минут.")


def test_extract_builds_verified_case(registry, case_reply):
    [c] = extract_cases(ART, FakeLLM([case_reply()]), registry, D, 12000)
    assert c.level == Level.RF_REGIONS and c.methodology == Methodology.R1
    assert c.metrics[0].quote_verified and c.metrics[0].source_url == "https://gubernia74.ru/news/1"
    assert c.flags == [Flag.CONFIRMATION_SKIPPED]
    assert c.first_seen == c.updated == D and len(c.id) == 12


def test_invented_number_is_flagged(registry, case_reply):
    [c] = extract_cases(ART, FakeLLM([case_reply(after="4 мин")]), registry, D, 12000)
    assert Flag.QUOTE_NOT_FOUND in c.flags


def test_non_case_article_returns_empty(registry):
    assert extract_cases(ART, FakeLLM([{"cases": []}]), registry, D, 12000) == []


def test_unknown_criterion_and_stage_are_coerced(registry, case_reply):
    [c] = extract_cases(ART, FakeLLM([case_reply(criterion="удобство", stage="запущен")]), registry, D, 12000)
    assert c.metrics[0].criterion == OTHER_CRITERION and c.stage == Stage.UNKNOWN


def test_bad_structure_raises(registry):
    with pytest.raises(LLMFormatError):
        extract_cases(ART, FakeLLM([{"items": []}]), registry, D, 12000)


def test_article_text_is_truncated(registry):
    llm = FakeLLM([{"cases": []}])
    extract_cases(ART, llm, registry, D, 20)
    assert "13 до 5" not in llm.log[0][1]


def test_sverdlovsk_and_business_methodology():
    assert infer_level("Россия", "Свердловская обл.") == Level.SVERDLOVSK
    assert infer_level("РФ", "г. Екатеринбург") == Level.SVERDLOVSK
    assert infer_level("Германия", None) == Level.WORLD
    assert select_methodology(Level.WORLD, Sector.BUSINESS) == Methodology.BUSINESS
    assert select_methodology(Level.WORLD, Sector.GOV) == Methodology.M1
    assert select_methodology(Level.SVERDLOVSK, Sector.GOV) == Methodology.R1


def test_methodology_prompt_lists_all_criteria():
    p = methodology_prompt()
    for crits in CRITERIA.values():
        for c in crits:
            assert c in p


def test_single_case_without_wrapper_is_accepted(registry, case_reply):
    [c] = extract_cases(ART, FakeLLM([case_reply()["cases"][0]]), registry, D, 12000)
    assert c.metrics[0].quote_verified


def test_top_level_list_is_accepted(registry, case_reply):
    assert len(extract_cases(ART, FakeLLM([case_reply()["cases"]]), registry, D, 12000)) == 1


def test_derived_after_value_is_dropped_when_change_is_quoted(registry, case_reply):
    art = Article(url="https://gov.ru/1", domain="gov.ru", title="",
                  text="Число долгих ремонтов сократилось почти на четверть (23%).")
    r = case_reply(before=None, after="77%", change="-23%", quote="сократилось почти на четверть (23%)")
    [c] = extract_cases(art, FakeLLM([r]), registry, D, 12000)
    m = c.metrics[0]
    assert m.after is None and m.change == "-23%" and m.quote_verified


def test_invented_change_is_not_rescued(registry, case_reply):
    r = case_reply(before="13 мин", after="5 мин", change="-70%")
    [c] = extract_cases(ART, FakeLLM([r]), registry, D, 12000)
    assert not c.metrics[0].quote_verified
