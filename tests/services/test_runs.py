import threading
from types import SimpleNamespace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from aidigest.config import Settings
from aidigest.models import Level
from aidigest.services import runs as runs_mod
from aidigest.services.runs import (
    REASON_CRASHED, REASON_INTERRUPTED, REASON_SPAWN_FAILED, AlreadyRunning, MonthExhausted, RunParams,
    RunService, RunStore,
)
from aidigest.usage import TavilyUsage

pytestmark = pytest.mark.pg

NOW = datetime(2026, 11, 15, 12, 0, 0)


class FakeProc:
    def __init__(self, code, gate):
        self.code, self.gate = code, gate

    def wait(self):
        if self.gate is not None:
            self.gate.wait(10)
        return self.code


class Clock:
    """Каждый вызов — на секунду позже, чтобы run_id и started не совпадали."""
    def __init__(self):
        self.t = NOW

    def __call__(self):
        self.t += timedelta(seconds=1)
        return self.t


@pytest.fixture
def popen_calls():
    return []


@pytest.fixture
def gate():
    ev = threading.Event()
    yield ev
    ev.set()  # отпускаем зависшие фейковые процессы


@pytest.fixture
def make_svc(pg, tmp_path, popen_calls, gate):
    created: list[RunService] = []

    def _make(popen=None, usage=None, token="t", fetch=None):
        svc = RunService(RunStore(pg), tmp_path / "data", Path("/proj"), Settings(), token,
                         popen=popen, now=Clock(), fetch_usage=fetch or (lambda t: usage))
        created.append(svc)
        return svc

    yield _make
    gate.set()
    for s in created:
        s.join_watchers()


@pytest.fixture
def svc_child(make_svc, popen_calls, gate):
    def _make(code=0, output="", block=False):
        def popen(argv, **kw):
            popen_calls.append(argv)
            kw["stdout"].write(output.encode("utf-8"))
            kw["stdout"].flush()
            return FakeProc(code, gate if block else None)
        return make_svc(popen=popen)
    return _make


@pytest.fixture
def svc_popen_raises(make_svc):
    def popen(argv, **kw):
        raise OSError("нет python")
    return make_svc(popen=popen)


@pytest.fixture
def svc_usage(make_svc, popen_calls):
    def _make(usage):
        def popen(argv, **kw):
            popen_calls.append(argv)
            return FakeProc(0, None)
        return make_svc(popen=popen, usage=usage)
    return _make


def test_start_spawns_and_finishes_ok(svc_child):
    svc = svc_child(code=0, output="Кейсов новых: 3\n")
    rid = svc.start()
    svc.join_watchers()
    r = svc.store.get(rid)
    assert r.state == "ok" and r.report == {"Кейсов новых": "3"} and "Кейсов новых" in svc.log(rid)
    assert r.exit_code == 0 and r.finished is not None and r.label == "успешно"


def test_params_go_to_argv_and_record(svc_child, popen_calls):
    svc = svc_child(code=0)
    rid = svc.start(RunParams(budget=5, levels=[Level.SVERDLOVSK], offline=True))
    assert popen_calls[0][3:] == ["run", "--budget", "5", "--levels", "Свердловская область", "--offline"]
    assert svc.store.get(rid).params == {"budget": 5, "levels": ["Свердловская область"], "offline": True}


def test_popen_gets_env_cwd_and_stdout(make_svc, tmp_path):
    seen = {}

    def popen(argv, **kw):
        seen.update(kw)
        return FakeProc(0, None)
    svc = make_svc(popen=popen)
    svc.start()
    assert seen["cwd"] == Path("/proj")
    assert seen["env"]["AIDIGEST_DATA_DIR"] == str(tmp_path / "data")
    assert seen["env"]["PYTHONIOENCODING"] == "utf-8" and seen["env"]["PYTHONUNBUFFERED"] == "1"
    assert seen["stdout"].closed  # дескриптор родителя закрыт после popen


def test_start_twice_raises(svc_child):
    svc = svc_child(code=0, block=True)
    svc.start()
    with pytest.raises(AlreadyRunning):
        svc.start()


def test_current_returns_record_and_log_tail(svc_child):
    out = "".join(f"строка {i}\n" for i in range(40))
    svc = svc_child(code=0, output=out, block=True)
    rid = svc.start()
    rec, tail = svc.current()
    assert rec.run_id == rid and rec.state == "running"
    assert len(tail) == 30 and tail[-1] == "строка 39"


def test_current_none_when_idle(svc_child):
    assert svc_child().current() is None


def test_limit_exit_code(svc_child):
    svc = svc_child(code=2, output="Причина: Месячный лимит кредитов Tavily исчерпан\n")
    rid = svc.start()
    svc.join_watchers()
    r = svc.store.get(rid)
    assert r.state == "limit" and r.reason == "Месячный лимит кредитов Tavily исчерпан"


def test_crash_without_reason_marks_error(svc_child):
    svc = svc_child(code=-9, output="Traceback ...\n")
    rid = svc.start()
    svc.join_watchers()
    r = svc.store.get(rid)
    assert r.state == "error" and r.reason == REASON_CRASHED
    svc.start()  # кнопка снова доступна


def test_popen_failure_closes_record(svc_popen_raises):
    with pytest.raises(OSError):
        svc_popen_raises.start()
    assert svc_popen_raises.store.current() is None
    assert svc_popen_raises.store.history(1)[0].reason == REASON_SPAWN_FAILED


def test_month_exhausted_refuses(svc_usage):
    svc = svc_usage(TavilyUsage(used=1000, limit=1000))
    with pytest.raises(MonthExhausted):
        svc.start()
    assert svc.store.history() == []


def test_month_exhausted_allows_offline(svc_usage):
    svc = svc_usage(TavilyUsage(used=1000, limit=1000))
    assert svc.start(RunParams(offline=True))


def test_unknown_usage_allows_start(svc_usage):
    svc = svc_usage(None)
    assert svc.credits()["known"] is False and svc.start()


def test_credits_values(svc_usage):
    c = svc_usage(TavilyUsage(used=40, limit=1000, plan="Researcher")).credits()
    assert c == {"known": True, "used": 40, "limit": 1000, "remaining": 960, "plan": "Researcher",
                 "run_budget": 30}


def test_credits_without_token_does_not_fetch(make_svc):
    def boom(token):
        raise AssertionError("не должен вызываться")
    c = make_svc(token=None, fetch=boom).credits()
    assert c["known"] is False and c["remaining"] is None


def test_credits_cached_including_none(make_svc):
    calls = []

    def fetch(token):
        calls.append(token)
        return None
    svc = make_svc(fetch=fetch)
    svc.credits()
    svc.credits()
    assert len(calls) == 1


def test_credits_cache_expires(make_svc, monkeypatch):
    calls = []
    clock = [1000.0]
    monkeypatch.setattr(runs_mod, "time", SimpleNamespace(monotonic=lambda: clock[0], sleep=lambda s: None))
    svc = make_svc(fetch=lambda t: calls.append(t))
    svc.credits()
    clock[0] += 61
    svc.credits()
    assert len(calls) == 2


def test_on_startup_interrupts_left_running(svc_child):
    svc = svc_child(code=0)
    svc.store.create("old", NOW, {})
    assert svc.on_startup() == 1
    r = svc.store.get("old")
    assert r.reason == REASON_INTERRUPTED and r.state == "interrupted" and r.finished is not None


def test_log_missing(svc_child):
    svc = svc_child()
    assert svc.log("нет") is None
    svc.store.create("x", NOW, {})
    assert svc.log("x") is None  # записи есть, файла нет


def test_prune_removes_old_logs(svc_child, monkeypatch):
    monkeypatch.setattr(runs_mod, "RUNS_KEEP", 2)
    svc = svc_child(code=0, output="Кейсов новых: 1\n")
    ids = []
    for _ in range(3):
        ids.append(svc.start())
        svc.join_watchers()
    assert [r.run_id for r in svc.history()] == [ids[2], ids[1]]
    assert sorted(p.stem for p in (svc.data_dir / "runs").glob("*.log")) == sorted(ids[1:])


def test_store_roundtrip_times_and_minutes(pg):
    store = RunStore(pg)
    store.create("a", NOW, {})
    assert store.get("a").started == NOW
    assert store.finish("a", "ok", 0, None, {}, NOW + timedelta(minutes=7, seconds=30))
    r = store.get("a")
    assert r.finished == NOW + timedelta(minutes=7, seconds=30) and r.minutes == 7
    assert not store.finish("a", "error", 1, "x", {}, NOW)  # повторно не закрывается


def test_run_params_argv_empty_and_days():
    assert RunParams().to_argv() == [] and RunParams().as_dict() == {}
    assert RunParams(days=3, budget=2.5).to_argv() == ["--budget", "2.5", "--days", "3"]


def test_watcher_retries_finish_after_db_error(svc_child, monkeypatch):
    monkeypatch.setattr(runs_mod, "FINISH_PAUSE", 0)
    svc = svc_child(code=0, output="Кейсов новых: 2\n")
    real, calls = svc.store.finish, []

    def flaky(*a, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("обрыв соединения")
        return real(*a, **kw)
    monkeypatch.setattr(svc.store, "finish", flaky)
    rid = svc.start()
    svc.join_watchers()
    assert len(calls) == 2
    assert svc.store.get(rid).state == "ok" and svc.store.current() is None


def test_watcher_cleanup_error_keeps_result(svc_child, monkeypatch):
    svc = svc_child(code=0)
    monkeypatch.setattr(svc.store, "prune", lambda keep: (_ for _ in ()).throw(RuntimeError("x")))
    rid = svc.start()
    svc.join_watchers()
    assert svc.store.get(rid).state == "ok"


def test_mkdir_failure_leaves_no_running_record(svc_child, monkeypatch):
    svc = svc_child(code=0)
    monkeypatch.setattr(Path, "mkdir", lambda self, **kw: (_ for _ in ()).throw(OSError("диск")))
    with pytest.raises(OSError):
        svc.start()
    assert svc.store.current() is None
    assert svc.store.history(1)[0].reason == REASON_SPAWN_FAILED
