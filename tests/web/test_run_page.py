import json
from datetime import datetime
from types import SimpleNamespace

from aidigest_web import create_app
from aidigest_web.runs import RunManager

NOW = datetime(2026, 11, 8, 14, 32, 0)


def make(data_dir):
    popen_calls = []

    def popen(args, **kw):
        popen_calls.append(args)
        return SimpleNamespace(pid=4242)
    rm = RunManager(data_dir, data_dir / "root", popen=popen, now=lambda: NOW)
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


def test_run_page_prefers_tavily_numbers(data_dir):
    from aidigest.usage import TavilyUsage
    client, _, rm = make(data_dir)
    rm._tavily = lambda: TavilyUsage(used=210, limit=1000, plan="Researcher")
    body = html(client.get("/run"))
    assert "210" in body and "по данным Tavily" in body and "1-го числа" not in body


def test_run_page_falls_back_to_local_counter(data_dir):
    (data_dir / "credits.json").write_text(json.dumps({"2026-11": 150}), encoding="utf-8")
    client, _, rm = make(data_dir)
    rm._tavily = lambda: None
    body = html(client.get("/run"))
    assert "150" in body and "по нашему учёту" in body


def test_tavily_exhausted_blocks_start(data_dir):
    import pytest
    from aidigest.usage import TavilyUsage
    from aidigest_web.runs import MonthExhausted
    _, calls, rm = make(data_dir)
    rm._tavily = lambda: TavilyUsage(used=1000, limit=1000, plan="p")
    with pytest.raises(MonthExhausted):
        rm.start()
    assert calls == []


def test_running_without_log_lines_explains_wait(data_dir):
    client, _, rm = make(data_dir)
    rm.start()
    body = html(client.get("/run"))
    assert "Запускается…" not in body and "появятся после первого поискового запроса" in body


def write_result(data_dir, run_id, **extra):
    runs = data_dir / "web" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"{run_id}.json").write_text(json.dumps({
        "run_id": run_id, "started": NOW.isoformat(), "finished": NOW.isoformat(), "exit_code": 1,
        "state": "error", **extra}), encoding="utf-8")


def test_run_page_shows_reason(data_dir):
    client, _, _ = make(data_dir)
    write_result(data_dir, "20261107-100000", reason="Причина постарше.")
    write_result(data_dir, "20261108-100000", reason="Tavily недоступен — проверьте ключ.")
    body = html(client.get("/run"))
    assert '<p class="error">Tavily недоступен — проверьте ключ.</p>' in body
    assert "Причина постарше." in body  # причина в таблице истории
    assert "подробности в логе" not in body


def test_run_page_error_without_reason_points_to_log(data_dir):
    client, _, _ = make(data_dir)
    write_result(data_dir, "20261108-100000")
    assert "Сбор завершился с ошибкой — подробности в логе." in html(client.get("/run"))


def test_interrupted_run_shows_reason_instead_of_generic_text(data_dir):
    client, _, _ = make(data_dir)
    write_result(data_dir, "20261108-100000", state="interrupted", exit_code=None, reason="Сбор оборвался (тест).")
    body = html(client.get("/run"))
    assert "Сбор оборвался (тест)." in body and "выключили компьютер" not in body
