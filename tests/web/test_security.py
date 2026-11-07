"""Исправления по финальному ревью фронта."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

from aidigest.store import CaseStore, StoreData
from aidigest_web import create_app
from aidigest_web.runs import RunManager

NOW = datetime(2026, 11, 8, 14, 32, 0)


def app_with_fake_runs(data_dir, password=None, alive=True, now=NOW):
    calls = []
    rm = RunManager(data_dir, data_dir / "root", popen=lambda a, **k: calls.append(a) or SimpleNamespace(pid=4242),
                    pid_alive=lambda pid: alive, now=lambda: now)
    app = create_app(data_dir, password=password, secret_key="t", run_manager=rm)
    return app.test_client(), calls, rm


def test_cross_site_post_cannot_start_run(data_dir):
    client, calls, _ = app_with_fake_runs(data_dir)
    assert client.post("/run", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/run", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert calls == []
    assert client.post("/run", headers={"Origin": "http://localhost", "Sec-Fetch-Site": "same-origin"}).status_code == 302
    assert len(calls) == 1


def test_foreign_host_rejected_without_password(data_dir):
    client, _, _ = app_with_fake_runs(data_dir)
    assert client.get("/", headers={"Host": "attacker.example:8000"}).status_code == 400
    assert client.get("/", headers={"Host": "127.0.0.1:8000"}).status_code == 200


def test_javascript_urls_are_not_rendered_as_links(tmp_path, make_case, make_metric):
    from aidigest.models import Source
    bad = "javascript:alert(document.cookie)"
    c = make_case(id="x", metrics=[make_metric(source_url=bad, confirmed_by=[bad])],
                  sources=[Source(url=bad, domain="evil")])
    CaseStore(tmp_path / "cases.json").save(StoreData([c], set()))
    body = create_app(tmp_path, password=None, secret_key="t").test_client().get("/case/x").get_data(as_text=True)
    assert 'href="javascript:' not in body and "javascript:history" not in body


def test_empty_cases_file_does_not_crash(tmp_path):
    (tmp_path / "cases.json").write_text("", encoding="utf-8")
    client = create_app(tmp_path, password=None, secret_key="t").test_client()
    r = client.get("/")
    assert r.status_code == 200 and "Кейсов пока нет" in r.get_data(as_text=True)
    assert client.get("/export.xlsx").status_code == 200


def test_very_old_lock_is_treated_as_interrupted(tmp_path):
    _, _, rm = app_with_fake_runs(tmp_path)
    rm.start()
    later = RunManager(tmp_path, tmp_path / "root", pid_alive=lambda pid: True, now=lambda: NOW + timedelta(hours=4))
    assert later.current() is None and later.history()[0].state == "interrupted"


def test_malformed_lock_and_history_do_not_crash(tmp_path):
    rm = RunManager(tmp_path, tmp_path / "root", pid_alive=lambda pid: True, now=lambda: NOW)
    (tmp_path / "web" / "runs").mkdir(parents=True)
    (tmp_path / "web" / "run.lock").write_text(json.dumps({"run_id": "20261108-143200"}), encoding="utf-8")
    (tmp_path / "web" / "runs" / "bad.json").write_text("{}", encoding="utf-8")
    assert rm.current() is None and rm.history() == []


def test_export_leaves_no_temp_files(client, tmp_path, monkeypatch):
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    assert client.get("/export.xlsx").status_code == 200
    assert not list(tmp_path.glob("aidigest_web_*"))


def test_runner_binds_child_and_hides_window(tmp_path, monkeypatch):
    import sys
    import aidigest_web.runner as runner
    seen = {}

    class FakeProc:
        pid = 1

        def __init__(self, args, **kw):
            seen["kw"] = kw
            kw["stdout"].write(b"ok\n")

        def wait(self):
            return 0
    monkeypatch.setattr(runner.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(runner, "_kill_children_with_runner", lambda: seen.setdefault("bound", True))
    monkeypatch.setenv("AIDIGEST_DATA_DIR", str(tmp_path))
    assert runner.main(["20261108-143200"]) == 0
    assert seen["bound"] is True
    if sys.platform == "win32":
        import subprocess
        assert seen["kw"]["creationflags"] & subprocess.CREATE_NO_WINDOW
