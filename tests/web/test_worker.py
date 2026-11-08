import json
import os
import time
from datetime import datetime

import aidigest_web.worker as worker
from aidigest_web.runs import RunManager

from test_runs import NOW, FakePopen, heartbeat


def queue_manager(tmp_path, popen):
    return RunManager(tmp_path, tmp_path / "root", popen=popen, now=lambda: NOW, clock=time.time, mode="queue")


class FakeRun:
    def __init__(self, code=0):
        self.calls = []
        self.code = code

    def __call__(self, argv):
        self.calls.append(argv)
        return self.code


def test_queue_start_writes_request_not_process(tmp_path):
    popen = FakePopen()
    info = queue_manager(tmp_path, popen).start()
    assert popen.calls == []
    request = tmp_path / "web" / "requests" / f"{info.run_id}.json"
    assert json.loads(request.read_text(encoding="utf-8")) == {"run_id": info.run_id}
    lock = json.loads((tmp_path / "web" / "run.lock").read_text(encoding="utf-8"))
    assert lock == {"run_id": info.run_id, "started": NOW.isoformat(), "mode": "queue"}


def test_process_once_runs_request(tmp_path):
    info = queue_manager(tmp_path, FakePopen()).start()
    fake, events = FakeRun(), []
    got = worker.process_once(tmp_path, run=fake, before=lambda: events.append("before"),
                              after=lambda code: events.append(("after", code)))
    assert got == info.run_id
    assert fake.calls == [[info.run_id]]
    assert events == ["before", ("after", 0)]
    assert not (tmp_path / "web" / "requests" / f"{info.run_id}.json").exists()


def test_process_once_skips_cancelled_request(tmp_path):
    info = queue_manager(tmp_path, FakePopen()).start()
    (tmp_path / "web" / "run.lock").unlink()
    fake = FakeRun()
    assert worker.process_once(tmp_path, run=fake) is None
    assert fake.calls == []
    assert not (tmp_path / "web" / "requests" / f"{info.run_id}.json").exists()


def test_process_once_without_requests(tmp_path):
    fake = FakeRun()
    assert worker.process_once(tmp_path, run=fake) is None
    assert fake.calls == []


def test_process_once_takes_oldest_request(tmp_path):
    requests = tmp_path / "web" / "requests"
    requests.mkdir(parents=True)
    for run_id in ("20261108-150000", "20261108-140000"):
        (requests / f"{run_id}.json").write_text(json.dumps({"run_id": run_id}), encoding="utf-8")
    (tmp_path / "web" / "run.lock").write_text(json.dumps(
        {"run_id": "20261108-140000", "started": NOW.isoformat(), "mode": "queue"}), encoding="utf-8")
    fake = FakeRun()
    assert worker.process_once(tmp_path, run=fake) == "20261108-140000"
    assert [p.name for p in requests.iterdir()] == ["20261108-150000.json"]


def test_status_busy_and_idle(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AIDIGEST_DATA_DIR", str(tmp_path))
    assert worker.main(["--status"]) == 0
    assert capsys.readouterr().out.strip() == "idle"

    run_id = datetime.now().replace(microsecond=0).strftime("%Y%m%d-%H%M%S")
    (tmp_path / "web" / "runs").mkdir(parents=True)
    (tmp_path / "web" / "run.lock").write_text(json.dumps(
        {"run_id": run_id, "started": datetime.now().replace(microsecond=0).isoformat(), "mode": "queue"}),
        encoding="utf-8")
    heartbeat(tmp_path, run_id)
    assert worker.main(["--status"]) == 1
    assert capsys.readouterr().out.strip() == "busy"


def test_status_is_read_only_for_stale_run(tmp_path, monkeypatch, capsys):
    # deploy.sh спрашивает статус из другого процесса: проверка не должна снимать блокировку
    monkeypatch.setenv("AIDIGEST_DATA_DIR", str(tmp_path))
    run_id = datetime.now().replace(microsecond=0).strftime("%Y%m%d-%H%M%S")
    runs = tmp_path / "web" / "runs"
    runs.mkdir(parents=True)
    lock = tmp_path / "web" / "run.lock"
    lock.write_text(json.dumps(
        {"run_id": run_id, "started": datetime.now().replace(microsecond=0).isoformat(), "mode": "queue"}),
        encoding="utf-8")
    old = time.time() - 600
    os.utime(heartbeat(tmp_path, run_id), (old, old))
    assert worker.main(["--status"]) == 0
    assert capsys.readouterr().out.strip() == "idle"
    assert lock.exists()
    assert not (runs / f"{run_id}.json").exists()


def test_loop_survives_failed_request(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AIDIGEST_DATA_DIR", str(tmp_path))
    calls = []

    def boom(data_dir, **kw):
        calls.append(data_dir)
        raise RuntimeError("сломалось")

    monkeypatch.setattr(worker, "process_once", boom)
    assert worker.loop(tmp_path, iterations=2, sleep=lambda s: None) == 0
    assert len(calls) == 2
    assert "сломалось" in capsys.readouterr().err


def test_create_app_passes_run_mode(tmp_path):
    from aidigest_web import create_app
    app = create_app(tmp_path, password=None, secret_key="test", run_mode="queue")
    assert app.extensions["runs"].mode == "queue"


def test_main_rejects_unknown_run_mode(monkeypatch, capsys):
    import aidigest_web.__main__ as web_main
    monkeypatch.setenv("AIDIGEST_RUN_MODE", "cloud")
    monkeypatch.setattr(web_main, "_web_env", lambda: {})
    monkeypatch.setattr(web_main, "_serve", lambda *a: (_ for _ in ()).throw(AssertionError("не должен стартовать")))
    assert web_main.main([]) == 2
    assert "AIDIGEST_RUN_MODE" in capsys.readouterr().out


def _run_files(runs, run_id, suffixes=(".json", ".log", ".heartbeat")):
    for suffix in suffixes:
        (runs / f"{run_id}{suffix}").write_text("{}", encoding="utf-8")


def test_prune_runs_removes_all_files_of_old_runs(tmp_path):
    runs = tmp_path / "web" / "runs"
    runs.mkdir(parents=True)
    ids = [f"20261108-{i:06d}" for i in range(5)]
    for run_id in ids:
        _run_files(runs, run_id)
    (runs / f"{ids[0]}.pid").write_text("1", encoding="utf-8")  # старый формат
    assert worker.prune_runs(tmp_path, keep=3) == 7
    assert sorted({p.name.split(".")[0] for p in runs.iterdir()}) == ids[2:]
    assert len(list(runs.iterdir())) == 9


def test_prune_runs_without_runs_dir(tmp_path):
    assert worker.prune_runs(tmp_path) == 0


def test_housekeep_cleans_cache_runs_and_exports(tmp_path):
    now = time.time()
    old = tmp_path / "cache" / "tavily" / "old.json"
    old.parent.mkdir(parents=True)
    old.write_text("{}", encoding="utf-8")
    os.utime(old, (now - 30 * 86400, now - 30 * 86400))
    out = tmp_path / "out"
    out.mkdir()
    for day in range(1, 33):
        (out / f"cases_2026-10-{day:02d}.xlsx").write_text("x", encoding="utf-8")
    runs = tmp_path / "web" / "runs"
    runs.mkdir(parents=True)
    for i in range(102):
        _run_files(runs, f"20261108-{i:06d}", (".json",))
    worker.housekeep(tmp_path)
    assert not old.exists()
    assert len(list(out.glob("*.xlsx"))) == 30
    assert len(list(runs.iterdir())) == 100


def test_process_once_touches_heartbeat_before_lock_check(tmp_path, monkeypatch):
    info = queue_manager(tmp_path, FakePopen()).start()
    beat = tmp_path / "web" / "runs" / f"{info.run_id}.heartbeat"
    seen = []
    real = worker._lock_run_id

    def spy(data_dir):
        seen.append(beat.exists())
        return real(data_dir)

    monkeypatch.setattr(worker, "_lock_run_id", spy)
    assert worker.process_once(tmp_path, run=FakeRun()) == info.run_id
    assert seen == [True]


def test_process_once_removes_heartbeat_of_skipped_request(tmp_path):
    info = queue_manager(tmp_path, FakePopen()).start()
    (tmp_path / "web" / "run.lock").unlink()
    assert worker.process_once(tmp_path, run=FakeRun()) is None
    assert not (tmp_path / "web" / "runs" / f"{info.run_id}.heartbeat").exists()


def test_process_once_goes_past_skipped_requests(tmp_path):
    requests = tmp_path / "web" / "requests"
    requests.mkdir(parents=True)
    for run_id in ("20261108-140000", "20261108-150000"):
        (requests / f"{run_id}.json").write_text(json.dumps({"run_id": run_id}), encoding="utf-8")
    (tmp_path / "web" / "run.lock").write_text(json.dumps(
        {"run_id": "20261108-150000", "started": NOW.isoformat(), "mode": "queue"}), encoding="utf-8")
    fake = FakeRun()
    assert worker.process_once(tmp_path, run=fake) == "20261108-150000"
    assert fake.calls == [["20261108-150000"]]
    assert list(requests.iterdir()) == []


def test_main_wires_housekeep_and_backup(tmp_path, monkeypatch):
    monkeypatch.setenv("AIDIGEST_DATA_DIR", str(tmp_path))
    got = {}

    def fake_loop(data_dir, **kw):
        got.update(kw)
        return 0

    monkeypatch.setattr(worker, "loop", fake_loop)
    assert worker.main([]) == 0
    (tmp_path / "cases.json").write_text("{}", encoding="utf-8")
    got["after"](1)
    assert not (tmp_path / "backups").exists()
    got["after"](0)
    assert len(list((tmp_path / "backups").glob("cases_*.json"))) == 1
    (tmp_path / "out").mkdir()
    got["before"]()  # очистка на пустой папке не падает


def test_before_hook_error_does_not_block_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AIDIGEST_DATA_DIR", str(tmp_path))
    got = {}
    monkeypatch.setattr(worker, "loop", lambda data_dir, **kw: got.update(kw) or 0)

    def broken(data_dir):
        raise OSError("диск занят")

    monkeypatch.setattr(worker, "housekeep", broken)
    worker.main([])
    got["before"]()
    assert "диск занят" in capsys.readouterr().err
