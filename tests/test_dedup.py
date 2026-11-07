from datetime import date

from aidigest.dedup import find_duplicate, merge_into
from aidigest.models import ConfirmationStatus, Flag, Level, Stage
from fakes import FakeLLM


def test_no_candidates_no_llm_call(make_case):
    llm = FakeLLM([])
    assert find_duplicate(make_case(region="Татарстан"), [make_case(region="Белгородская область")], llm) is None
    assert llm.calls == 0


def test_other_level_is_not_candidate(make_case):
    llm = FakeLLM([])
    old = make_case(id="old", region="Свердловская область", level=Level.SVERDLOVSK)
    assert find_duplicate(make_case(region="Свердловская область"), [old], llm) is None
    assert llm.calls == 0


def test_llm_picks_duplicate(make_case):
    old = make_case(id="old", region="Белгородская область", ai_technology="цифровой двойник водоснабжения")
    new = make_case(region="Белгородская обл", ai_technology="цифровой двойник")
    assert find_duplicate(new, [old], FakeLLM([{"duplicate_id": "old"}])).id == "old"
    assert find_duplicate(new, [old], FakeLLM([{"duplicate_id": "чужой"}])) is None
    assert find_duplicate(new, [old], FakeLLM([{"duplicate_id": None}])) is None


def test_candidates_limited_and_prioritised(make_case):
    olds = [make_case(id=f"o{i}", region="Татарстан", ai_technology="чат-бот", title=f"x{i}") for i in range(7)]
    best = make_case(id="best", region="Татарстан", ai_technology="ГосПромпт помощник", title="ГосПромпт")
    llm = FakeLLM([{"duplicate_id": None}])
    find_duplicate(make_case(region="Татарстан", ai_technology="ГосПромпт", title="ГосПромпт"), olds + [best], llm)
    prompt = llm.log[0][1]
    assert '"best"' in prompt and prompt.count('"id"') == 6  # новый кейс + 5 кандидатов


def test_merge_same_metric_other_domain_confirms(make_case, make_metric, make_source):
    t = make_case(stage=Stage.PILOT,
                  metrics=[make_metric(criterion="качество", before=None, after=None, change="-23%",
                                       source_url="https://chr.rbc.ru/1")],
                  sources=[make_source("https://chr.rbc.ru/1")])
    n = make_case(stage=Stage.DEPLOYED,
                  metrics=[make_metric(criterion="качество", before=None, after=None, change="23%",
                                       source_url="https://itrussia.media/2")],
                  sources=[make_source("https://itrussia.media/2")])
    merge_into(t, n, date(2026, 11, 7))
    assert t.metrics[0].confirmed_by == ["https://itrussia.media/2"] and len(t.metrics) == 1
    assert t.stage == Stage.DEPLOYED and len(t.sources) == 2 and t.updated == date(2026, 11, 7)
    assert t.confirmation_status == ConfirmationStatus.CONFIRMED
    assert Flag.CONFIRMATION_SKIPPED not in t.flags


def test_merge_same_domain_does_not_confirm(make_case, make_metric, make_source):
    t = make_case(metrics=[make_metric(source_url="https://chr.rbc.ru/1")], sources=[make_source("https://chr.rbc.ru/1")])
    n = make_case(metrics=[make_metric(source_url="https://chr.rbc.ru/2")], sources=[make_source("https://chr.rbc.ru/2")])
    merge_into(t, n, date(2026, 11, 7))
    assert t.metrics[0].confirmed_by == [] and t.confirmation_status == ConfirmationStatus.SINGLE


def test_merge_new_metric_is_appended(make_case, make_metric):
    t = make_case(metrics=[make_metric()])
    n = make_case(metrics=[make_metric(name="ДТП", before="161", after="122", source_url="https://chel.kp.ru/1")])
    merge_into(t, n, date(2026, 11, 7))
    assert len(t.metrics) == 2


def test_merge_keeps_more_mature_stage(make_case):
    t = make_case(stage=Stage.SCALING)
    merge_into(t, make_case(stage=Stage.UNKNOWN), date(2026, 11, 7))
    assert t.stage == Stage.SCALING
