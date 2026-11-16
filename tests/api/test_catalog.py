import pytest

pytestmark = pytest.mark.pg


def test_queries(authed):
    b = authed.get("/api/queries").json()
    assert b["total"] > 0 and b["error"] is None and b["freshness_days"] > 0
    assert b["groups"][0]["level"] and b["groups"][0]["queries"]


def test_sources_and_filters(authed):
    b = authed.get("/api/sources").json()
    assert b["total"] > 0 and b["error"] is None and len(b["sources"]) == b["total"]
    assert {"value": "rf", "label": "регионы РФ и Свердловская область"} in b["level_options"]
    assert {"value": "мир", "label": "мир"} in b["level_options"]
    assert {"value": "высокая", "label": "высокая"} in b["reliability_options"]
    hi = authed.get("/api/sources", params={"reliability": "высокая"}).json()
    assert 0 < len(hi["sources"]) < b["total"] and hi["total"] == b["total"]
