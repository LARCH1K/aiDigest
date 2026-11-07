"""Вход по одному общему паролю (WEB_PASSWORD в web.env)."""
from __future__ import annotations

import hmac
from urllib.parse import urlsplit

from flask import Flask, abort, current_app, redirect, render_template, request, session, url_for

OPEN_ENDPOINTS = {"login", "static"}
LOCAL_NAMES = {"localhost", "127.0.0.1", "[::1]"}


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
            expected = current_app.config["WEB_PASSWORD"] or ""
            given = request.form.get("password", "")
            if hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8")):
                session["auth"] = True
                return redirect(_safe_next(request.args.get("next")))
            error = "Неверный пароль"
        return render_template("login.html", error=error)
