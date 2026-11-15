from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path
from subprocess import TimeoutExpired
from threading import Barrier, Event

import pytest
from fastapi.testclient import TestClient

from aidigest.config import Settings
from aidigest.services.runs import REASON_INTERRUPTED, RunService, RunStore
from aidigest.usage import TavilyUsage
from aidigest_api import create_app

pytestmark = pytest.mark.pg

BUSY = "Сбор уже идёт — дождитесь, пока он закончится."


def test_start_run_and_conflict(authed_blocking_child):
    c = authed_blocking_child
    r = c.post("/api/runs")
    assert r.status_code == 202 and r.json()["run_id"]
    cur = c.get("/api/runs/current").json()
    assert cur["running"] is True and cur["run_id"] == r.json()["run_id"] and cur["tail"] == []
    assert isinstance(cur["minutes"], int) and "T" in cur["started"]
    r2 = c.post("/api/runs")
    assert r2.status_code == 409 and r2.json() == {"detail": BUSY}


def test_simultaneous_starts_return_one_conflict(authed_blocking_child, monkeypatch, popen_calls):
    client = authed_blocking_child
    service = client.app.state.run_service
    now = datetime(2026, 11, 15, 12)
    barrier = Barrier(2)
    issued_ids = []
    create = service.store.create

    def record_id(run_id, started, params):
        issued_ids.append(run_id)
        return create(run_id, started, params)

    def start():
        barrier.wait(5)
        return client.post("/api/runs")

    monkeypatch.setattr(service, "_now", lambda: now)
    monkeypatch.setattr(service.store, "create", record_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        requests = [pool.submit(start) for _ in range(2)]
        responses = sorted((request.result() for request in requests), key=lambda r: r.status_code)
    assert [r.status_code for r in responses] == [202, 409]
    assert responses[1].json() == {"detail": BUSY}
    assert len(popen_calls) == 1
    assert len(set(issued_ids)) == 2
    assert all(run_id.startswith(now.strftime("%Y%m%d-%H%M%S")) for run_id in issued_ids)


@pytest.mark.parametrize(("child_state", "expected_signals", "expected_result"), [
    ("running", ["terminate", "wait"], ("interrupted", REASON_INTERRUPTED, None)),
    ("ignores_terminate", ["terminate", "wait", "kill", "wait"], ("interrupted", REASON_INTERRUPTED, None)),
    ("exited", [], ("ok", None, 0)),
])
def test_lifespan_finishes_child(pg, tmp_path, child_state, expected_signals, expected_result):
    exited = Event()
    signals = []

    class Child:
        def wait(self, timeout=None):
            if timeout is not None:
                assert timeout > 0
                signals.append("wait")
                if not exited.is_set():
                    raise TimeoutExpired("test-child", timeout)
            else:
                assert exited.wait(5)
            return 0 if child_state == "exited" else 1

        def poll(self):
            if child_state == "exited":
                exited.set()
                return 0
            return None

        def terminate(self):
            signals.append("terminate")
            if child_state != "ignores_terminate":
                exited.set()

        def kill(self):
            signals.append("kill")
            exited.set()

    store = RunStore(pg)
    service = RunService(store, tmp_path, Path("/proj"), Settings(), None, popen=lambda *a, **kw: Child())
    app = create_app(pg, username=None, password=None, secret_key=None, run_service=service)
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post("/api/runs")
        assert response.status_code == 202
        run_id = response.json()["run_id"]
        assert store.get(run_id).state == "running"
    assert signals == expected_signals
    record = store.get(run_id)
    assert (record.state, record.reason, record.exit_code) == expected_result
    assert record.finished is not None and store.current() is None


def test_month_exhausted(authed):
    svc = authed.app.state.run_service
    svc.tavily_token = "t"
    svc._fetch_usage = lambda t: TavilyUsage(used=1000, limit=1000, plan="x")
    r = authed.post("/api/runs")
    assert r.status_code == 409
    assert r.json() == {"detail": "Лимит кредитов Tavily исчерпан — новый сбор возможен после пополнения лимита."}


def test_credits(authed):
    svc = authed.app.state.run_service
    svc.tavily_token = "t"
    svc._fetch_usage = lambda t: TavilyUsage(used=10, limit=1000, plan="x")
    assert authed.get("/api/credits").json()["remaining"] == 990


def test_start_run_without_body_and_history(authed, popen_calls):
    rid = authed.post("/api/runs").json()["run_id"]
    authed.app.state.run_service.join_watchers()
    assert popen_calls[0][3:] == ["run"]
    h = authed.get("/api/runs?limit=5").json()
    assert h[0]["run_id"] == rid and h[0]["state"] == "ok" and h[0]["label"] == "успешно"
    assert set(h[0]) == {"run_id", "state", "label", "started", "finished", "minutes", "exit_code", "reason",
                         "report", "params"}


def test_start_run_passes_debug_params(authed, popen_calls):
    r = authed.post("/api/runs", json={"budget": 5, "levels": ["Свердловская область"], "offline": True})
    assert r.status_code == 202
    assert popen_calls[0][3:] == ["run", "--budget", "5", "--levels", "Свердловская область", "--offline"]


@pytest.mark.parametrize("body", [
    {"budget": -1}, {"budget": True}, {"budget": "5"}, {"levels": ["марс"]},
    {"levels": "мир"}, {"days": 0}, {"days": 1.0}, {"days": "1"},
    {"offline": 1}, {"offline": "true"}, {"unknown": True}, [],
    {"budget": None}, {"days": None}, {"levels": None},
])
def test_start_run_rejects_bad_params(authed, body):
    assert authed.post("/api/runs", json=body).status_code == 422
    assert authed.get("/api/runs").json() == []


def test_start_run_rejects_nonfinite_budget(authed, popen_calls):
    r = authed.post("/api/runs", content='{"budget":1e400}', headers={"Content-Type": "application/json"})
    assert r.status_code == 422 and not popen_calls


def test_start_run_rejects_explicit_null(authed, popen_calls):
    r = authed.post("/api/runs", content="null", headers={"Content-Type": "application/json"})
    assert r.status_code == 422 and not popen_calls


def test_start_run_rejects_days_before_earliest_supported_date(authed, popen_calls):
    max_days = (date.today() - date.min).days
    assert authed.post("/api/runs", json={"days": max_days + 1}).status_code == 422
    assert not popen_calls and authed.get("/api/runs").json() == []
    assert authed.post("/api/runs", json={"days": max_days}).status_code == 202
    assert popen_calls[0][-2:] == ["--days", str(max_days)]


@pytest.mark.parametrize("limit", ["0", "-1", "1.0", "1.5", "no"])
def test_history_rejects_bad_limit(authed, limit):
    assert authed.get("/api/runs", params={"limit": limit}).status_code == 422


def test_run_log(authed):
    rid = authed.post("/api/runs").json()["run_id"]
    authed.app.state.run_service.join_watchers()
    r = authed.get(f"/api/runs/{rid}/log")
    assert r.status_code == 200 and r.headers["content-type"] == "text/plain; charset=utf-8"
    assert authed.get("/api/runs/нет/log").status_code == 404
