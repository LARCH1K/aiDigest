from aidigest.models import Case, ConfirmationStatus, Flag, Stage


def test_flags_for_fresh_case_with_unverified_metric(make_case, make_metric):
    c = make_case(metrics=[make_metric(quote_verified=False)], stage=Stage.UNKNOWN)
    assert set(c.flags) == {Flag.QUOTE_NOT_FOUND, Flag.STAGE_UNCLEAR, Flag.CONFIRMATION_SKIPPED}


def test_no_metrics_case_has_no_confirmation_flags(make_case):
    c = make_case(metrics=[], stage=Stage.PILOT)
    assert c.flags == [Flag.NO_METRICS]


def test_recompute_status_conflict_wins(make_case, make_metric):
    c = make_case(metrics=[make_metric(confirmed_by=["https://a.ru/1"]),
                           make_metric(conflicting_values=["161 (https://b.ru)"])])
    c.recompute_status()
    assert c.confirmation_status == ConfirmationStatus.CONFLICT and Flag.SOURCES_CONFLICT in c.flags


def test_recompute_status_confirmed(make_case, make_metric):
    c = make_case(metrics=[make_metric(confirmed_by=["https://a.ru/1"])])
    c.recompute_status()
    assert c.confirmation_status == ConfirmationStatus.CONFIRMED


def test_single_source_flag_only_after_attempt(make_case):
    c = make_case(confirmation_attempts=1)
    assert Flag.SINGLE_SOURCE in c.flags and Flag.CONFIRMATION_SKIPPED not in c.flags


def test_case_json_roundtrip_keeps_russian_values(make_case):
    c = make_case()
    raw = c.model_dump_json()
    assert "регионы РФ" in raw and "цифра" not in raw
    assert Case.model_validate_json(raw) == c


def test_stage_order_is_maturity():
    assert list(Stage) == [Stage.UNKNOWN, Stage.DEVELOPMENT, Stage.PILOT, Stage.DEPLOYED, Stage.SCALING]
