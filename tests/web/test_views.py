from aidigest.models import ConfirmationStatus, Flag, Level
from aidigest_web.views import FLAG_HELP, STATUS_CLASS, filter_cases, headline

from webdata import sample_cases


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
