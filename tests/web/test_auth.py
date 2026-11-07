import aidigest_web.__main__ as web_main


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
    monkeypatch.setattr(web_main, "_web_env", lambda: {"WEB_PASSWORD": "x"})
    monkeypatch.setenv("AIDIGEST_DATA_DIR", str(tmp_path))
    assert web_main.main(["--host", "0.0.0.0", "--port", "8080"]) == 0 and served == [("0.0.0.0", 8080)]
