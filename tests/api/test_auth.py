from datetime import datetime

import pytest

from aidigest.services.runs import RunStore

pytestmark = pytest.mark.pg


def test_healthz_open_and_plain(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.text == "ok" and r.headers["content-type"].startswith("text/plain")


def test_api_requires_login(client):
    r = client.get("/api/cases")
    assert r.status_code == 401 and r.json() == {"detail": "нужен вход"}


def test_me_reports_state(client):
    assert client.get("/api/me").json() == {"authenticated": False, "login_required": True}
    client.post("/api/login", json={"username": "u", "password": "p"})
    assert client.get("/api/me").json() == {"authenticated": True, "login_required": True}
    assert client.post("/api/logout").status_code == 204
    assert client.get("/api/me").json()["authenticated"] is False
    assert client.get("/api/cases").status_code == 401


def test_me_without_password(open_client):
    assert open_client.get("/api/me").json() == {"authenticated": True, "login_required": False}


def test_login_cookie_not_secure_by_default(client):
    r = client.post("/api/login", json={"username": "u", "password": "p"})
    cookie = r.headers["set-cookie"].lower()
    assert r.status_code == 204 and "aidigest_session=" in cookie and "secure" not in cookie
    assert "samesite=strict" in cookie


def test_login_cookie_secure_when_enabled(secure_client):
    r = secure_client.post("/api/login", json={"username": "u", "password": "p"})
    assert "secure" in r.headers["set-cookie"].lower()


@pytest.mark.parametrize("body", [{"username": "u", "password": "x"}, {"username": "x", "password": "p"}])
def test_wrong_credentials(client, body):
    r = client.post("/api/login", json=body)
    assert r.status_code == 401 and r.json() == {"detail": "Неверный логин или пароль"}


def test_wrong_password_then_block(client):
    for _ in range(10):
        client.post("/api/login", json={"username": "u", "password": "x"})
    r = client.post("/api/login", json={"username": "u", "password": "p"})
    assert r.status_code == 429 and r.json() == {"detail": "Слишком много неудачных попыток. Подождите 10 минут."}


@pytest.mark.parametrize(("trust_real_ip", "expected"), [(False, 429), (True, 204)])
def test_limiter_uses_real_ip_only_in_trusted_mode(make_client, trust_real_ip, expected):
    client = make_client(trust_real_ip=trust_real_ip)
    for _ in range(10):
        client.post("/api/login", json={"username": "u", "password": "x"}, headers={"X-Real-IP": "1.1.1.1"})
    assert client.post("/api/login", json={"username": "u", "password": "p"},
                       headers={"X-Real-IP": "2.2.2.2"}).status_code == expected


def test_cross_site_post_rejected(authed):
    assert authed.post("/api/runs", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert authed.post("/api/runs", headers={"Origin": "http://evil.test"}).status_code == 403
    assert authed.get("/api/runs").json() == []


def test_same_origin_post_allowed(authed):
    r = authed.post("/api/runs", json={"offline": True},
                    headers={"Sec-Fetch-Site": "same-origin", "Origin": "http://testserver"})
    assert r.status_code == 202


def test_foreign_host_rejected_without_password(open_client):
    assert open_client.get("/api/cases", headers={"Host": "evil.test"}).status_code == 400
    assert open_client.get("/api/cases").status_code == 200  # без пароля всё открыто на localhost


def test_foreign_host_ok_with_password(client):
    assert client.get("/api/me", headers={"Host": "example.org"}).status_code == 200


def test_startup_interrupts_left_running(pg, make_client):
    RunStore(pg).create("old", datetime.now(), {})
    make_client()
    assert RunStore(pg).get("old").state == "interrupted"
