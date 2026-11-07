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
    [c] = extract_cases(ART, FakeLLM([case_reply(criterion="удобство", name="индекс", stage="запущен")]), registry, D, 12000)
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


def test_invented_change_is_removed_not_kept(registry, case_reply):
    r = case_reply(before="13 мин", after="5 мин", change="-70%")
    [c] = extract_cases(ART, FakeLLM([r]), registry, D, 12000)
    m = c.metrics[0]
    assert m.quote_verified and m.change is None and (m.before, m.after) == ("13 мин", "5 мин")


# --- пакет «к показу»: отсев не-кейсов, федеральный уровень, критерии ---
from aidigest.methodology import guess_criterion


def test_llm_marked_non_case_is_dropped_with_reason(registry, case_reply):
    r = case_reply()
    r["cases"][0]["is_concrete"] = False
    r["cases"][0]["not_concrete_reason"] = "отраслевая статистика, а не проект"
    rejected = []
    assert extract_cases(ART, FakeLLM([r]), registry, D, 12000, rejected=rejected) == []
    assert rejected == ["т: отраслевая статистика, а не проект"]


def test_case_without_implementer_and_place_is_dropped(registry, case_reply):
    r = case_reply(country=None, region=None, organization=None, title="План закупок ТЭК")
    rejected = []
    assert extract_cases(ART, FakeLLM([r]), registry, D, 12000, rejected=rejected) == []
    assert "не указано, кто и где внедрил" in rejected[0]


def test_russian_case_without_region_is_federal(registry, case_reply):
    [c] = extract_cases(ART, FakeLLM([case_reply(region=None, organization="Минфин России")]), registry, D, 12000)
    assert c.level == Level.RF_REGIONS and c.region == "федеральный уровень"


def test_world_case_keeps_empty_region(registry, case_reply):
    [c] = extract_cases(ART, FakeLLM([case_reply(country="Германия", region=None, organization="Digitalservice")]),
                        registry, D, 12000)
    assert c.region is None


def test_guess_criterion_by_keywords():
    assert guess_criterion("экономия затрат на персонал", Methodology.BUSINESS) == "операционные затраты"
    assert guess_criterion("сокращение времени обработки заявок", Methodology.BUSINESS) == "время процесса"
    assert guess_criterion("доля ошибок в документах", Methodology.BUSINESS) == "уровень ошибок"
    assert guess_criterion("окупаемость инвестиций", Methodology.BUSINESS) == "ROI"
    assert guess_criterion("время ожидания ответа", Methodology.R1) == "скорость"
    assert guess_criterion("экономия бюджета", Methodology.R1) == "экономическая эффективность"
    assert guess_criterion("точность прогноза", Methodology.R1) == "качество"
    assert guess_criterion("число пользователей", Methodology.M1) == "реализуемость и масштаб"
    assert guess_criterion("что-то непонятное", Methodology.R1) == OTHER_CRITERION


def test_unknown_criterion_is_mapped_by_metric_name(registry, case_reply):
    r = case_reply(sector="бизнес", organization="X5", name="экономия затрат на логистику", criterion="эффективность",
                   before=None, after=None, change="-20%", quote="затраты на логистику снизились на 20%")
    art = Article(url="https://x5.ru/1", domain="x5.ru", title="", text="В X5 затраты на логистику снизились на 20%.")
    [c] = extract_cases(art, FakeLLM([r]), registry, D, 12000)
    assert c.metrics[0].criterion == "операционные затраты"


def test_derived_change_is_dropped_when_before_after_are_quoted(registry, case_reply):
    art = Article(url="https://oblgazeta.ru/1", domain="oblgazeta.ru", title="",
                  text="Если в 2023 году на 10 тыс. сотрудников приходилось 16 промышленных роботов, то в 2025 году — уже 23.")
    r = case_reply(region="Свердловская область", name="плотность роботизации", before="16", after="23", change="+43.8%",
                   quote="на 10 тыс. сотрудников приходилось 16 промышленных роботов, то в 2025 году — уже 23")
    [c] = extract_cases(art, FakeLLM([r]), registry, D, 12000)
    m = c.metrics[0]
    assert m.quote_verified and m.change is None and (m.before, m.after) == ("16", "23")


def test_nothing_rescued_when_quote_is_absent(registry, case_reply):
    r = case_reply(before="10", after="2", change="-80%", quote="время сократилось с 10 до 2 минут")
    [c] = extract_cases(ART, FakeLLM([r]), registry, D, 12000)
    assert not c.metrics[0].quote_verified and c.metrics[0].change == "-80%"


# --- ревью quality-pass ---

def test_sverdlovsk_detected_from_municipality_or_org(registry, case_reply):
    r = case_reply(region=None)
    r["cases"][0]["municipality"] = "Екатеринбург"
    [c] = extract_cases(ART, FakeLLM([r]), registry, D, 12000)
    assert c.level == Level.SVERDLOVSK and c.region != "федеральный уровень"
    r2 = case_reply(region=None, organization="Правительство Свердловской области")
    [c2] = extract_cases(ART, FakeLLM([r2]), registry, D, 12000)
    assert c2.level == Level.SVERDLOVSK


def test_city_case_without_region_is_not_federal(registry, case_reply):
    r = case_reply(region=None, organization=None)
    r["cases"][0]["municipality"] = "Казань"
    [c] = extract_cases(ART, FakeLLM([r]), registry, D, 12000)
    assert c.region is None and c.municipality == "Казань"


def test_country_only_world_case_is_kept(registry, case_reply):
    [c] = extract_cases(ART, FakeLLM([case_reply(country="Эстония", region=None, organization=None)]), registry, D, 12000)
    assert c.level == Level.WORLD and c.country == "Эстония"


def test_explicit_other_criterion_is_kept(registry, case_reply):
    [c] = extract_cases(ART, FakeLLM([case_reply(criterion="прочее")]), registry, D, 12000)
    assert c.metrics[0].criterion == OTHER_CRITERION


def test_guess_criterion_matches_word_starts():
    assert guess_criterion("протяжённость трубопровода", Methodology.R1) == OTHER_CRITERION


def test_is_concrete_string_false_is_respected(registry, case_reply):
    r = case_reply()
    r["cases"][0]["is_concrete"] = "false"
    assert extract_cases(ART, FakeLLM([r]), registry, D, 12000) == []
