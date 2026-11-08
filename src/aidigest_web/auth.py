"""Вход по одному общему паролю (WEB_PASSWORD в web.env)."""
from __future__ import annotations

import hmac
import threading
import time
from urllib.parse import urlsplit

from flask import Flask, abort, current_app, redirect, render_template, request, session, url_for

OPEN_ENDPOINTS = {"login", "static", "healthz"}
LOCAL_NAMES = {"localhost", "127.0.0.1", "[::1]"}


BLOCKED_TEXT = "Слишком много неудачных попыток. Подождите 10 минут."


class LoginLimiter:
    """Счётчик неудачных входов по IP: после max_failures за window секунд вход закрыт до конца окна.

    Сайт работает в нескольких потоках waitress, поэтому все операции под замком.
    Старые отметки выбрасываются при каждом обращении — память не растёт без предела."""

    def __init__(self, max_failures: int = 10, window: float = 600, clock=time.monotonic):
        self.max_failures = max_failures
        self.window = window
        self._clock = clock
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        cutoff = now - self.window
        for ip in list(self._failures):
            fresh = [t for t in self._failures[ip] if t > cutoff]
            if fresh:
                self._failures[ip] = fresh
            else:
                del self._failures[ip]

    def blocked(self, ip: str) -> bool:
        with self._lock:
            self._prune(self._clock())
            return len(self._failures.get(ip, ())) >= self.max_failures

    def failed(self, ip: str) -> None:
        with self._lock:
            now = self._clock()
            self._prune(now)
            self._failures.setdefault(ip, []).append(now)

    def reset(self, ip: str) -> None:
        with self._lock:
            self._failures.pop(ip, None)


def _hostname(host: str) -> str:
    if host.startswith("["):
        return host.split("]")[0] + "]"
    return host.rsplit(":", 1)[0].lower()


def _safe_next(target: str | None) -> str:
    """Только относительные пути внутри сайта — не даём увести пользователя на чужой адрес."""
    if not target:
        return "/"
    parts = urlsplit(target)
    if parts.scheme or parts.netloc or not target.startswith("/") or target.startswith("//"):
        return "/"
    return target


def init(app: Flask) -> None:
    app.extensions["login_limiter"] = LoginLimiter()

    @app.before_request
    def guard_requests():
        """Без пароля сайт отвечает только по локальному имени (защита от подмены DNS),
        а формы принимаются только со своего же сайта (защита от чужих страниц, жмущих «Запустить»)."""
        if not current_app.config["WEB_PASSWORD"] and _hostname(request.host) not in LOCAL_NAMES:
            abort(400)
        if request.method == "POST":
            site = request.headers.get("Sec-Fetch-Site")
            if site and site not in ("same-origin", "none"):
                abort(403)
            origin = request.headers.get("Origin")
            if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
                abort(403)
        return None

    @app.before_request
    def require_login():
        if not current_app.config["WEB_PASSWORD"] or request.endpoint in OPEN_ENDPOINTS:
            return None
        if session.get("auth"):
            return None
        return redirect(url_for("login", next=request.full_path.rstrip("?")))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        if request.method == "POST":
            limiter: LoginLimiter = current_app.extensions["login_limiter"]
            ip = request.remote_addr or ""
            # При блокировке пароль не проверяется: ответ не выдаёт, был ли он верным.
            if limiter.blocked(ip):
                return render_template("login.html", error=BLOCKED_TEXT), 429
            expected = current_app.config["WEB_PASSWORD"] or ""
            given = request.form.get("password", "")
            if hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8")):
                limiter.reset(ip)
                session["auth"] = True
                return redirect(_safe_next(request.args.get("next")))
            limiter.failed(ip)
            error = "Неверный пароль"
        return render_template("login.html", error=error)
