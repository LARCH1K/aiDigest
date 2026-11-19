from types import SimpleNamespace
from unittest.mock import Mock

from aidigest_api.schemas import RunQuery

from aidigest_api import create_app
from aidigest_api.routes import api_routes


def test_default_api_does_not_load_tavily_credentials(monkeypatch):
    load_creds = Mock(return_value={"TAVILY_TOKEN": "test"})
    monkeypatch.setattr("aidigest_api.load_creds", load_creds)
    monkeypatch.delenv("AIDIGEST_SEARCH_PROVIDER", raising=False)
    kwargs = dict(username=None, password=None, secret_key=None)
    default_app = create_app(Mock(), **kwargs)
    assert default_app.state.run_service.credits()["known"] is False
    load_creds.assert_not_called()

    monkeypatch.setenv("AIDIGEST_SEARCH_PROVIDER", "tavily")
    tavily_app = create_app(Mock(), **kwargs)
    assert tavily_app.state.run_service.tavily_token == "test"
    assert load_creds.call_args.args[0].name == "secrets.env"


def test_old_run_logs_hide_provider_names():
    run = SimpleNamespace(run_id="test", started="2026-11-19T00:00:00", minutes=1)
    text = "Причина: Tavily недоступен"
    runs = Mock()
    runs.current.return_value = run, [text]
    runs.log.return_value = text
    runs.history.return_value = [{
        "run_id": "test", "state": "error", "label": "ошибка", "started": run.started,
        "finished": run.started, "minutes": 1, "exit_code": 1, "reason": text,
        "report": {"Кредитов Tavily потрачено": "1"}, "params": {},
    }]
    router = api_routes(Mock(), Mock(), runs)
    endpoints = {route.name: route.endpoint for route in router.routes}
    history = endpoints["run_history"](RunQuery())[0].model_dump_json()
    current = endpoints["current_run"]().model_dump_json()
    log = endpoints["run_log"]("test")
    for body in (history, current, log):
        assert "tavily" not in body.lower()
        assert "недоступен" in body
