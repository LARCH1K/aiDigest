import aidigest_web.__main__ as web_main
from aidigest.creds import WEB_KEYS, load_creds


def test_pages_open_without_password(client):
    assert client.get("/").status_code == 200


def test_password_redirects_to_login(protected_client):
    r = protected_client.get("/")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_static_is_open_without_login(protected_client):
    assert protected_client.get("/static/style.css").status_code == 200


def test_wrong_password_rejected(protected_client):
    r = protected_client.post("/login", data={"password": "не тот"})
    assert r.status_code == 200 and "Неверный пароль" in r.get_data(as_text=True)
    assert protected_client.get("/").status_code == 302


def test_right_password_lets_in(protected_client):
    r = protected_client.post("/login?next=/help", data={"password": "секрет"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/help")
    assert protected_client.get("/").status_code == 200


def test_login_does_not_redirect_offsite(protected_client):
    r = protected_client.post("/login?next=https://evil.example/", data={"password": "секрет"})
    assert r.headers["Location"].endswith("/")


def test_main_refuses_network_without_password(monkeypatch, tmp_path):
    served = []
    monkeypatch.setattr(web_main, "_serve", lambda app, host, port: served.append((host, port)))
    monkeypatch.setattr(web_main, "_web_env", lambda: {})
    monkeypatch.setenv("AIDIGEST_DATA_DIR", str(tmp_path))
    assert web_main.main(["--host", "0.0.0.0"]) == 2 and served == []
    assert web_main.main([]) == 0 and served == [("127.0.0.1", 8000)]


def test_main_allows_network_with_password(monkeypatch, tmp_path):
    served = []
    monkeypatch.setattr(web_main, "_serve", lambda app, host, port: served.append((host, port)))
    monkeypatch.setattr(web_main, "_web_env", lambda: {"WEB_PASSWORD": "x", "WEB_SECRET_KEY": "k"})
    monkeypatch.setenv("AIDIGEST_DATA_DIR", str(tmp_path))
    assert web_main.main(["--host", "0.0.0.0", "--port", "8080"]) == 0 and served == [("0.0.0.0", 8080)]



def test_main_refuses_network_without_secret_key(monkeypatch, tmp_path):
    served = []
    monkeypatch.setattr(web_main, "_serve", lambda app, host, port: served.append((host, port)))
    # Вместо настоящего web.env — несуществующий файл: ключи берутся только из переменных.
    monkeypatch.setattr(web_main, "_web_env", lambda: load_creds(tmp_path / "web.env", WEB_KEYS))
    monkeypatch.setenv("WEB_PASSWORD", "x")
    monkeypatch.delenv("WEB_SECRET_KEY", raising=False)
    monkeypatch.setenv("AIDIGEST_DATA_DIR", str(tmp_path))
    assert web_main.main(["--host", "0.0.0.0"]) == 2 and served == []


def test_healthz_open_without_login(protected_client):
    r = protected_client.get("/healthz")
    assert r.status_code == 200 and r.data == b"ok"


def test_login_blocked_after_10_failures(protected_client):
    for _ in range(10):
        assert protected_client.post("/login", data={"password": "не тот"}).status_code == 200
    r = protected_client.post("/login", data={"password": "секрет"})
    assert r.status_code == 429
    assert "Слишком много неудачных попыток. Подождите 10 минут." in r.get_data(as_text=True)
    assert protected_client.get("/").status_code == 302


def test_successful_login_resets_failures(protected_client):
    for _ in range(9):
        protected_client.post("/login", data={"password": "не тот"})
    assert protected_client.post("/login", data={"password": "секрет"}).status_code == 302
    for _ in range(9):
        assert protected_client.post("/login", data={"password": "не тот"}).status_code == 200


def test_login_limiter_window_expires():
    from aidigest_web.auth import LoginLimiter
    now = [1000.0]
    limiter = LoginLimiter(clock=lambda: now[0])
    for _ in range(10):
        limiter.failed("1.2.3.4")
    assert limiter.blocked("1.2.3.4") and not limiter.blocked("5.6.7.8")
    now[0] += 601
    assert not limiter.blocked("1.2.3.4")
    limiter.failed("1.2.3.4")
    limiter.reset("1.2.3.4")
    assert not limiter.blocked("1.2.3.4")


def test_main_reads_trust_proxy(monkeypatch, tmp_path):
    apps = []
    monkeypatch.setattr(web_main, "_serve", lambda app, host, port: apps.append(app))
    monkeypatch.setattr(web_main, "_web_env", lambda: {})
    monkeypatch.setenv("AIDIGEST_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AIDIGEST_TRUST_PROXY", "1")
    monkeypatch.delenv("AIDIGEST_RUN_MODE", raising=False)
    assert web_main.main([]) == 0 and apps[-1].config["SESSION_COOKIE_SECURE"] is True
    monkeypatch.setenv("AIDIGEST_TRUST_PROXY", "0")
    assert web_main.main([]) == 0 and not apps[-1].config["SESSION_COOKIE_SECURE"]
