import json
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


def manager(tmp_path, alive=True, popen=None):
    return RunManager(tmp_path, tmp_path / "root", popen=popen or FakePopen(), pid_alive=lambda pid: alive,
                      now=lambda: NOW)


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


def test_dead_pid_without_result_is_interrupted(tmp_path):
    info = manager(tmp_path).start()
    m = manager(tmp_path, alive=False)
    assert m.current() is None
    assert m.history()[0].run_id == info.run_id and m.history()[0].state == "interrupted"
    m.start()  # снова можно запускать


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


def test_runner_pid_file_overrides_launcher_pid(tmp_path):
    info = manager(tmp_path).start()
    (tmp_path / "web" / "runs" / f"{info.run_id}.pid").write_text("777", encoding="utf-8")
    m = RunManager(tmp_path, tmp_path / "root", pid_alive=lambda pid: pid == 777, now=lambda: NOW)
    assert m.current() is not None  # запускалка (4242) мертва, но настоящая обёртка (777) жива
    m2 = RunManager(tmp_path, tmp_path / "root", pid_alive=lambda pid: pid == 4242, now=lambda: NOW)
    assert m2.current() is None and m2.history()[0].state == "interrupted"


def test_runner_binds_itself_before_spawning_and_writes_pid(tmp_path, monkeypatch):
    order = []

    class FakeProc:
        def __init__(self, args, **kw):
            order.append("spawn")

        def wait(self):
            return 0
    monkeypatch.setattr(runner.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(runner, "_kill_children_with_runner", lambda: order.append("bind"))
    monkeypatch.setenv("AIDIGEST_DATA_DIR", str(tmp_path))
    runner.main(["20261108-143200"])
    assert order == ["bind", "spawn"]
    assert (tmp_path / "web" / "runs" / "20261108-143200.pid").read_text(encoding="utf-8").strip().isdigit()


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
