from datetime import date, datetime

import pytest

from aidigest.store import PgCaseStore, StoreData

pytestmark = pytest.mark.pg


def ids(resp):
    return [x["id"] for x in resp.json()["cases"]]


def test_empty_base_everything_answers(authed):
    assert authed.get("/api/cases").json() == {"total": 0, "updated": None, "cases": []}
    assert authed.get("/api/runs/current").json() == {"running": False}
    assert authed.get("/api/runs").json() == []
    assert authed.get("/api/credits").json()["known"] is False
    assert authed.get("/api/export.xlsx").status_code == 200


def test_meta(authed):
    m = authed.get("/api/meta").json()
    assert m["levels"] == ["мир", "регионы РФ", "Свердловская область"]
    assert {"value": "подтверждено", "label": "подтверждено", "class": "ok"} in m["statuses"]
    assert m["reliability"][0] == {"value": "высокая", "label": "высокая"}
    assert len(m["flag_help"]) == 7
    assert all(len(v) == 2 for v in m["flag_help"].values())


def test_case_list_default_includes_cases_without_metrics(pg, authed_with_cases):
    body = authed_with_cases.get("/api/cases").json()
    assert body["total"] == 3
    assert datetime.fromisoformat(body["updated"]) == PgCaseStore(pg).updated_at()
    assert [c["id"] for c in body["cases"]] == ["chel", "ekb", "bcg"]
    chel = next(c for c in body["cases"] if c["id"] == "chel")
    assert chel["status_label"] == "подтверждено" and chel["status_class"] == "ok"
    assert chel["headline"].startswith("время в пробках") and chel["headline_unverified"] is False
    assert chel["reliability"] == "средняя" and chel["reliability_class"] == "warn"
    assert chel["first_seen"] == "2026-11-01" and chel["flags"] == []


def test_cases_without_processed_urls_have_no_update_timestamp(pg, authed, make_case):
    PgCaseStore(pg).save(StoreData(cases=[make_case()]))
    body = authed.get("/api/cases").json()
    assert body["total"] == 1 and body["updated"] is None


def test_case_list_filters(authed_with_cases):
    c = authed_with_cases
    assert set(ids(c.get("/api/cases?metrics=0"))) == {"chel", "ekb", "bcg"}
    assert ids(c.get("/api/cases?metrics=1")) == ["chel", "ekb"]
    assert ids(c.get("/api/cases", params={"level": "Свердловская область"})) == ["ekb"]
    assert ids(c.get("/api/cases", params={"q": "катюша"})) == ["ekb"]
    assert ids(c.get("/api/cases", params={"status": "подтверждено"})) == ["chel"]
    assert ids(c.get("/api/cases?doubtful=1")) == ["chel", "bcg"]  # у ekb цитата не найдена
    assert ids(c.get("/api/cases", params={"reliability": "none", "metrics": 0})) == []
    assert set(ids(c.get("/api/cases", params={"reliability": "средняя"}))) == {"chel", "ekb", "bcg"}
    assert set(ids(c.get("/api/cases", params={"reliability": "средняя", "metrics": "1"}))) == {"chel", "ekb"}


def test_case_detail(authed_with_cases):
    d = authed_with_cases.get("/api/cases/chel").json()
    assert d["id"] == "chel" and d["metrics"][0]["confirmed_by"] == ["https://chel.kp.ru/1"]
    assert d["status_label"] == "подтверждено" and d["status_class"] == "ok" and d["reliability_label"] == "средняя"


def test_case_not_found(authed_with_cases):
    r = authed_with_cases.get("/api/cases/нет")
    assert r.status_code == 404 and r.json() == {"detail": "Кейс не найден"}


def test_export_xlsx(authed_with_cases):
    r = authed_with_cases.get("/api/export.xlsx")
    assert r.status_code == 200 and r.content[:2] == b"PK"
    assert r.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert f'filename="aidigest_cases_{date.today().isoformat()}.xlsx"' in r.headers["content-disposition"]
