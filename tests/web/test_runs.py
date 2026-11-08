import json
import os
import time
from datetime import datetime
from types import SimpleNamespace

import pytest

import aidigest_web.runner as runner
from aidigest_web.runs import AlreadyRunning, MonthExhausted, RunManager, parse_report

NOW = datetime(2026, 11, 8, 14, 32, 0)


class FakePopen:
    def __init__(self):
        self.calls = []

    def __call__(self, args, **kw):
        self.calls.append((args, kw))
        return SimpleNamespace(pid=4242)


def manager(tmp_path, clock=time.time, popen=None):
    return RunManager(tmp_path, tmp_path / "root", popen=popen or FakePopen(), now=lambda: NOW, clock=clock)


def age(path, seconds):
    """Состарить файл: mtime на `seconds` раньше текущего времени."""
    t = time.time() - seconds
    os.utime(path, (t, t))


def heartbeat(tmp_path, run_id):
    p = tmp_path / "web" / "runs" / f"{run_id}.heartbeat"
    p.write_text("", encoding="utf-8")
    return p


def finish(tmp_path, run_id, code=0, state="ok"):
    (tmp_path / "web" / "runs" / f"{run_id}.json").write_text(json.dumps({
        "run_id": run_id, "started": NOW.isoformat(), "finished": NOW.isoformat(), "exit_code": code, "state": state,
    }), encoding="utf-8")


def test_start_creates_lock_and_spawns_runner(tmp_path):
    popen = FakePopen()
    info = manager(tmp_path, popen=popen).start()
    args, kw = popen.calls[0]
    assert args[1:] == ["-m", "aidigest_web.runner", info.run_id] and kw["cwd"] == str(tmp_path / "root")
    assert kw["env"]["AIDIGEST_DATA_DIR"] == str(tmp_path)
    assert info.run_id == "20261108-143200" and info.state == "running"
    assert json.loads((tmp_path / "web" / "run.lock").read_text(encoding="utf-8"))["pid"] == 4242


def test_second_start_is_rejected(tmp_path):
    popen = FakePopen()
    m = manager(tmp_path, popen=popen)
    m.start()
    with pytest.raises(AlreadyRunning):
        m.start()
    assert len(popen.calls) == 1 and m.current().state == "running"


def test_finished_run_releases_lock(tmp_path):
    m = manager(tmp_path)
    info = m.start()
    finish(tmp_path, info.run_id)
    assert m.current() is None and not (tmp_path / "web" / "run.lock").exists()
    assert m.history()[0].state == "ok"


def test_stale_heartbeat_is_interrupted(tmp_path):
    m = manager(tmp_path)
    info = m.start()
    age(heartbeat(tmp_path, info.run_id), 100)
    assert m.current() is None
    last = m.history()[0]
    assert last.run_id == info.run_id and last.state == "interrupted" and "оборвался" in last.reason
    m.start()  # снова можно запускать


def test_fresh_heartbeat_keeps_run_alive(tmp_path):
    m = manager(tmp_path)
    info = m.start()
    age(tmp_path / "web" / "run.lock", 1000)  # заявка давняя, но сборщик отчитывается
    age(heartbeat(tmp_path, info.run_id), 10)
    assert m.current().run_id == info.run_id


def test_no_heartbeat_young_lock_is_running(tmp_path):
    m = manager(tmp_path)
    info = m.start()
    assert m.current().run_id == info.run_id and m.history() == []


def test_no_heartbeat_old_lock_says_worker_missing(tmp_path):
    m = manager(tmp_path)
    info = m.start()
    age(tmp_path / "web" / "run.lock", 100)
    assert m.current() is None
    last = m.history()[0]
    assert last.run_id == info.run_id and last.state == "interrupted"
    assert "Сборщик не взял заявку" in last.reason


def test_clock_is_used_for_liveness(tmp_path):
    m = manager(tmp_path)
    info = m.start()
    hb_mtime = heartbeat(tmp_path, info.run_id).stat().st_mtime
    assert manager(tmp_path, clock=lambda: hb_mtime + 30).current() is not None
    assert manager(tmp_path, clock=lambda: hb_mtime + 120).current() is None


def test_old_result_without_reason_is_readable(tmp_path):
    (tmp_path / "web" / "runs").mkdir(parents=True)
    finish(tmp_path, "20261108-143200", code=1, state="error")
    run = manager(tmp_path).history()[0]
    assert run.state == "error" and run.reason is None


def test_month_exhausted_blocks_start(tmp_path):
    (tmp_path / "credits.json").write_text(json.dumps({"2026-11": 1000}), encoding="utf-8")
    m = manager(tmp_path)
    assert m.month_remaining() == 0
    with pytest.raises(MonthExhausted):
        m.start()


def test_parse_report_reads_cli_lines():
    log = ("Отсеян кандидат (https://x.ru): опрос\nКредитов Tavily потрачено: 7.0\nКейсов новых: 3\n"
           "Флаг: один_источник: 66\nExcel: D:\\x.xlsx\n")
    assert parse_report(log) == {"Кредитов Tavily потрачено": "7.0", "Кейсов новых": "3", "Флаг: один_источник": "66"}
    assert parse_report("Причина: Tavily недоступен\n") == {}


def test_history_includes_report_and_tail(tmp_path):
    m = manager(tmp_path)
    info = m.start()
    (tmp_path / "web" / "runs" / f"{info.run_id}.log").write_text("строка 1\nКейсов новых: 5\n", encoding="utf-8")
    finish(tmp_path, info.run_id)
    run = m.history()[0]
    assert run.report == {"Кейсов новых": "5"} and m.tail(run, 1) == ["Кейсов новых: 5"]


def test_runner_writes_result_json(tmp_path, monkeypatch):
    calls = []

    class FakeProc:
        _handle = 0

        def __init__(self, args, **kw):
            calls.append((args, kw))
            kw["stdout"].write("Кейсов новых: 1".encode("utf-8") + b"\n")

        def wait(self):
            return 2
    monkeypatch.setattr(runner.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(runner, "_kill_children_with_runner", lambda: None)
    monkeypatch.setenv("AIDIGEST_DATA_DIR", str(tmp_path))
    assert runner.main(["20261108-143200"]) == 2
    res = json.loads((tmp_path / "web" / "runs" / "20261108-143200.json").read_text(encoding="utf-8"))
    assert res["state"] == "limit" and res["exit_code"] == 2 and res["finished"]
    assert calls[0][0][1:] == ["-m", "aidigest", "run"]
    assert calls[0][1]["env"]["PYTHONIOENCODING"] == "utf-8"


def run_runner(tmp_path, monkeypatch, code, output=b""):
    class FakeProc:
        def __init__(self, args, **kw):
            kw["stdout"].write(output)

        def wait(self):
            return code
    monkeypatch.setattr(runner.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(runner, "_kill_children_with_runner", lambda: None)
    monkeypatch.setenv("AIDIGEST_DATA_DIR", str(tmp_path))
    assert runner.main(["20261108-143200"]) == code
    return json.loads((tmp_path / "web" / "runs" / "20261108-143200.json").read_text(encoding="utf-8"))


def test_runner_writes_heartbeat_and_reason(tmp_path, monkeypatch):
    out = "Причина: старая\nКейсов новых: 0\nПричина: Tavily недоступен — проверьте ключ.\n".encode("utf-8")
    res = run_runner(tmp_path, monkeypatch, 1, out)
    assert res["state"] == "error" and res["reason"].startswith("Tavily недоступен")
    runs = tmp_path / "web" / "runs"
    assert (runs / "20261108-143200.heartbeat").exists() and not (runs / "20261108-143200.pid").exists()


def test_runner_result_without_reason_line_is_null(tmp_path, monkeypatch):
    res = run_runner(tmp_path, monkeypatch, 0, b"ok\n")
    assert res["state"] == "ok" and res["reason"] is None


def test_runner_exit_code_3_is_busy(tmp_path, monkeypatch):
    assert run_runner(tmp_path, monkeypatch, 3)["state"] == "busy"
    assert RunManager(tmp_path, tmp_path / "root").history()[0].label == "уже шёл другой сбор"


def test_runner_heartbeat_thread_refreshes_file(tmp_path, monkeypatch):
    beats = []

    class FakeProc:
        def __init__(self, args, **kw):
            pass

        def wait(self):
            # ждём, пока фоновый поток обновит heartbeat хотя бы раз после первого
            for _ in range(200):
                if len(beats) >= 2:
                    break
                time.sleep(0.01)
            return 0
    real_touch = runner._touch
    monkeypatch.setattr(runner, "_touch", lambda p: (beats.append(p), real_touch(p)))
    monkeypatch.setattr(runner, "HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(runner.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(runner, "_kill_children_with_runner", lambda: None)
    monkeypatch.setenv("AIDIGEST_DATA_DIR", str(tmp_path))
    runner.main(["20261108-143200"])
    assert len(beats) >= 2
    n = len(beats)
    time.sleep(0.05)
    assert len(beats) == n  # после окончания сбора поток остановлен


def test_runner_binds_itself_before_spawning_and_writes_heartbeat(tmp_path, monkeypatch):
    order = []
    hb = tmp_path / "web" / "runs" / "20261108-143200.heartbeat"

    class FakeProc:
        def __init__(self, args, **kw):
            order.append("spawn")
            assert hb.exists()  # первое обновление — до запуска сбора

        def wait(self):
            return 0
    monkeypatch.setattr(runner.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(runner, "_kill_children_with_runner", lambda: order.append("bind"))
    monkeypatch.setenv("AIDIGEST_DATA_DIR", str(tmp_path))
    runner.main(["20261108-143200"])
    assert order == ["bind", "spawn"]


def test_runner_disables_output_buffering(tmp_path, monkeypatch):
    seen = {}

    class FakeProc:
        def __init__(self, args, **kw):
            seen["env"] = kw["env"]

        def wait(self):
            return 0
    monkeypatch.setattr(runner.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(runner, "_kill_children_with_runner", lambda: None)
    monkeypatch.setenv("AIDIGEST_DATA_DIR", str(tmp_path))
    runner.main(["20261108-143200"])
    assert seen["env"]["PYTHONUNBUFFERED"] == "1"
