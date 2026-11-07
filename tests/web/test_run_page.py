import json
from datetime import datetime
from types import SimpleNamespace

from aidigest_web import create_app
from aidigest_web.runs import RunManager

NOW = datetime(2026, 11, 8, 14, 32, 0)


def make(data_dir, alive=True):
    popen_calls = []

    def popen(args, **kw):
        popen_calls.append(args)
        return SimpleNamespace(pid=4242)
    rm = RunManager(data_dir, data_dir / "root", popen=popen, pid_alive=lambda pid: alive, now=lambda: NOW)
    app = create_app(data_dir, password=None, secret_key="t", run_manager=rm)
    return app.test_client(), popen_calls, rm


def html(r):
    return r.get_data(as_text=True)


def test_run_page_shows_credits_and_button(data_dir):
    (data_dir / "credits.json").write_text(json.dumps({"2026-11": 150}), encoding="utf-8")
    client, _, _ = make(data_dir)
    body = html(client.get("/run"))
    assert "150" in body and "1000" in body and "Запустить сбор" in body
    assert 'name="start"' in body and "disabled" not in body.split('name="start"')[1].split(">")[0]


def test_post_run_starts_once(data_dir):
    client, calls, _ = make(data_dir)
    r = client.post("/run", follow_redirects=True)
    assert "Сбор запущен" in html(r) and len(calls) == 1
    r = client.post("/run", follow_redirects=True)
    assert "Сбор уже идёт" in html(r) and len(calls) == 1
    assert "data-running" in html(client.get("/run"))


def test_button_disabled_when_month_exhausted(data_dir):
    (data_dir / "credits.json").write_text(json.dumps({"2026-11": 1000}), encoding="utf-8")
    client, calls, _ = make(data_dir)
    body = html(client.get("/run"))
    assert "disabled" in body.split('name="start"')[1].split(">")[0]
    r = client.post("/run", follow_redirects=True)
    assert "лимит" in html(r) and calls == []


def test_status_json_while_running(data_dir):
    client, _, rm = make(data_dir)
    info = rm.start()
    (data_dir / "web" / "runs" / f"{info.run_id}.log").write_text("строка А\nстрока Б\n", encoding="utf-8")
    st = client.get("/run/status").get_json()
    assert st["running"] is True and st["tail"] == ["строка А", "строка Б"]
    (data_dir / "web" / "runs" / f"{info.run_id}.json").write_text(json.dumps({
        "run_id": info.run_id, "started": NOW.isoformat(), "finished": NOW.isoformat(), "exit_code": 0, "state": "ok"}),
        encoding="utf-8")
    assert client.get("/run/status").get_json()["running"] is False


def test_history_shows_last_report(data_dir):
    client, _, rm = make(data_dir)
    info = rm.start()
    (data_dir / "web" / "runs" / f"{info.run_id}.log").write_text("Кейсов новых: 7\nКредитов Tavily потрачено: 12.0\n",
                                                                  encoding="utf-8")
    (data_dir / "web" / "runs" / f"{info.run_id}.json").write_text(json.dumps({
        "run_id": info.run_id, "started": NOW.isoformat(), "finished": NOW.isoformat(), "exit_code": 0, "state": "ok"}),
        encoding="utf-8")
    body = html(client.get("/run"))
    assert "Кейсов новых" in body and "7" in body and "успешно" in body
    log = client.get(f"/run/log/{info.run_id}")
    assert log.status_code == 200 and "Кредитов Tavily потрачено" in html(log)
    assert client.get("/run/log/..%2F..%2Fcredits").status_code == 404
