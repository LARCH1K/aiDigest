import json
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


def test_loop_survives_failed_request(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AIDIGEST_DATA_DIR", str(tmp_path))
    calls = []

    def boom(data_dir):
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
