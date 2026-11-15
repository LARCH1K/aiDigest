from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from aidigest_api import create_app
from aidigest_api import __main__ as cli


@pytest.fixture
def client():
    app = create_app(create_engine("sqlite://"), username="тест", password="пароль", secret_key="test-key",
                     run_service=SimpleNamespace())
    return TestClient(app, base_url="http://localhost:8000")


def test_health_without_database_connection(client):
    assert client.get("/healthz").text == "ok"


def test_auth_before_body_validation(client):
    r = client.post("/api/runs", content="{", headers={"Content-Type": "application/json"})
    assert r.status_code == 401 and r.json() == {"detail": "нужен вход"}


@pytest.mark.parametrize("origin", ["https://localhost", "http://localhost:9999", "null", "http://["])
def test_origin_must_match_forwarded_authority(client, origin):
    r = client.post("/api/login", headers={"Origin": origin}, json={"username": "тест", "password": "пароль"})
    assert r.status_code == 403


def test_proxy_https_origin_and_unicode_credentials(client):
    r = client.post("/api/login", headers={"Origin": "https://localhost:8000"},
                    json={"username": "тест", "password": "пароль"})
    assert r.status_code == 204
    assert client.get("/api/me").json() == {"authenticated": True, "login_required": True}


def test_invalid_login_does_not_echo_password(client):
    r = client.post("/api/login", json={"password": "sensitive-input"})
    assert r.status_code == 422 and "sensitive-input" not in r.text


def test_login_with_unpaired_surrogate_is_rejected(client):
    r = client.post("/api/login", content=r'{"username":"\ud800","password":"x"}',
                    headers={"Content-Type": "application/json"})
    assert r.status_code in {401, 422}


@pytest.mark.parametrize("path", ["/api/cases?metrics=true", "/api/cases?level=марс", "/api/sources?unknown=1"])
def test_invalid_filters(client, path):
    assert client.post("/api/login", json={"username": "тест", "password": "пароль"}).status_code == 204
    assert client.get(path).status_code == 422


@pytest.mark.parametrize(("credentials", "missing"), [
    ({"WEB_PASSWORD": "p", "WEB_SECRET_KEY": "s"}, "WEB_USERNAME"),
    ({"WEB_USERNAME": "u", "WEB_SECRET_KEY": "s"}, "WEB_PASSWORD"),
    ({"WEB_USERNAME": "u", "WEB_PASSWORD": "p"}, "WEB_SECRET_KEY"),
])
def test_cli_refuses_external_bind_without_credentials(monkeypatch, capsys, credentials, missing):
    monkeypatch.setattr(cli, "load_creds", lambda *_: credentials)
    assert cli.main(["--host", "0.0.0.0"]) == 2
    assert missing in capsys.readouterr().err


@pytest.mark.parametrize(("value", "trusted"), [(None, False), ("1", True)])
def test_cli_trusts_only_opted_in_nginx_ip_header(monkeypatch, value, trusted):
    monkeypatch.delenv("AIDIGEST_TRUST_REAL_IP", raising=False)
    if value is not None:
        monkeypatch.setenv("AIDIGEST_TRUST_REAL_IP", value)
    monkeypatch.setattr(cli, "load_creds", lambda *_: {})
    monkeypatch.setattr(cli, "make_engine", Mock())
    make_app = Mock()
    serve = Mock()
    monkeypatch.setattr(cli, "create_app", make_app)
    monkeypatch.setattr(cli.uvicorn, "run", serve)

    assert cli.main([]) == 0
    assert make_app.call_args.kwargs["trust_real_ip"] is trusted
    serve.assert_called_once_with(make_app.return_value, host="127.0.0.1", port=8000, workers=1, proxy_headers=False)
