"""Логика представления кейсов: фильтры, главная цифра, достоверность."""
from aidigest.models import ConfirmationStatus, Flag, Level
from aidigest.services.cases import FLAG_HELP, STATUS_CLASS, filter_cases, headline

from casedata import sample_cases


def ids(cases):
    return [c.id for c in cases]


def test_default_filter_keeps_only_cases_with_metrics():
    assert set(ids(filter_cases(sample_cases()))) == {"chel", "ekb"}
    assert len(filter_cases(sample_cases(), with_metrics=False)) == 3


def test_search_is_case_insensitive_and_yo_insensitive(make_case):
    cases = sample_cases() + [make_case(id="yo", title="Учёт ёмкостей", region="Пермский край")]
    assert ids(filter_cases(cases, q="ЕКАТЕРИНБУРГ", with_metrics=False)) == ["ekb"]
    assert ids(filter_cases(cases, q="учет емкостей", with_metrics=False)) == ["yo"]


def test_level_and_status_filters():
    assert ids(filter_cases(sample_cases(), level=Level.SVERDLOVSK.value)) == ["ekb"]
    assert ids(filter_cases(sample_cases(), status=ConfirmationStatus.CONFIRMED.value)) == ["chel"]


def test_hide_doubtful_drops_flagged():
    assert ids(filter_cases(sample_cases(), hide_doubtful=True)) == ["chel"]


def test_sort_matches_excel_order():
    assert ids(filter_cases(sample_cases(), with_metrics=False)) == ["chel", "ekb", "bcg"]


def test_headline_prefers_verified_metric(make_case, make_metric):
    c = make_case(metrics=[make_metric(name="охват", after="42%", before=None, quote_verified=False), make_metric()])
    assert headline(c) == ("время в пробках: 13 мин → 5 мин", False)


def test_headline_marks_unverified(make_case, make_metric):
    text, doubtful = headline(make_case(metrics=[make_metric(quote_verified=False)]))
    assert doubtful and text.startswith("время в пробках")


def test_headline_dash_without_metrics(make_case):
    assert headline(make_case(metrics=[])) == ("—", False)


def test_flag_help_covers_all_flags():
    assert set(FLAG_HELP) == set(Flag)
    assert all(meaning and action for meaning, action in FLAG_HELP.values())
    assert set(STATUS_CLASS) == set(ConfirmationStatus)


def test_headline_short_form(make_case, make_metric):
    m = make_metric(name="затраты", before=None, after=None, change="-20%")
    assert headline(make_case(metrics=[m])) == ("затраты: −20%".replace("−", "-"), False)
    m2 = make_metric(name="план", before=None, after="42%", change=None)
    assert headline(make_case(metrics=[m2]))[0] == "план: 42%"


def _src(url, rel):
    from aidigest.models import Source, SourceType
    from urllib.parse import urlsplit
    return Source(url=url, domain=urlsplit(url).hostname, reliability=rel, source_type=SourceType.MEDIA)


def test_best_reliability_prefers_high(make_case):
    from aidigest.models import Reliability
    from aidigest.services.cases import best_reliability
    c = make_case(sources=[_src("https://a.ru/1", Reliability.MEDIUM), _src("https://b.ru/1", Reliability.HIGH),
                           _src("https://c.ru/1", Reliability.UNRATED)])
    assert best_reliability(c) == Reliability.HIGH


def test_best_reliability_none_when_only_unrated(make_case):
    from aidigest.models import Reliability
    from aidigest.services.cases import RELIABILITY_LABEL, best_reliability
    c = make_case(sources=[_src("https://c.ru/1", Reliability.UNRATED)])
    assert best_reliability(c) is None and RELIABILITY_LABEL[None] == "нет оценённых"
    assert best_reliability(make_case(sources=[])) is None


def test_reliability_filter(make_case):
    from aidigest.models import Reliability
    cases = [make_case(id="hi", sources=[_src("https://a.ru/1", Reliability.HIGH)]),
             make_case(id="mid", sources=[_src("https://b.ru/1", Reliability.MEDIUM)]),
             make_case(id="none", sources=[_src("https://c.ru/1", Reliability.UNRATED)])]
    assert ids(filter_cases(cases, reliability="высокая")) == ["hi"]
    assert ids(filter_cases(cases, reliability="средняя")) == ["mid"]
    assert ids(filter_cases(cases, reliability="none")) == ["none"]
    assert len(filter_cases(cases, reliability="")) == 3
