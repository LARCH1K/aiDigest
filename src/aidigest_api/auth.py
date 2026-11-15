"""Подписанная сессия, ограничение попыток входа и проверка происхождения POST."""
from __future__ import annotations

import hmac
import re
import threading
import time
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from aidigest_api.schemas import LoginRequest, SessionState

BLOCKED_TEXT = "Слишком много неудачных попыток. Подождите 10 минут."
LOCAL_HOST = re.compile(r"(?:localhost|127\.0\.0\.1|\[::1\])(?::[0-9]+)?", re.IGNORECASE | re.ASCII)
OPEN_ROUTES = {("GET", "/healthz"), ("GET", "/api/me"), ("POST", "/api/login")}


class LoginLimiter:
    """Счётчик неудачных входов по IP за скользящее окно."""

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


def client_ip(request: Request, *, trust_real_ip: bool = False) -> str:
    forwarded_ip = request.headers.get("X-Real-IP") if trust_real_ip else None
    return forwarded_ip or (request.client.host if request.client else "")


def _same_origin(origin: str, host: str) -> bool:
    try:
        parts = urlsplit(origin)
    except ValueError:
        return False
    # За прокси схема запроса к API может отличаться от схемы в браузере.
    return (parts.scheme in {"http", "https"} and bool(parts.netloc)
            and parts.netloc.lower() == host.lower() and parts.username is None
            and parts.path in {"", "/"} and not parts.query and not parts.fragment)


def install_auth(app: FastAPI, *, username: str | None, password: str | None,
                 secret_key: str, secure_cookie: bool, trust_real_ip: bool) -> None:
    login_required = bool(password)
    limiter = LoginLimiter()

    def authenticated(request: Request) -> bool:
        return not login_required or request.session.get("auth") is True

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = request.headers.get("Host", "")
        if not login_required and not LOCAL_HOST.fullmatch(host):
            return JSONResponse({"detail": "Без пароля API доступен только локально"}, status_code=400)
        if request.method == "POST":
            site = request.headers.get("Sec-Fetch-Site")
            origin = request.headers.get("Origin")
            if ((site is not None and site not in {"same-origin", "none"})
                    or (origin is not None and not _same_origin(origin, host))):
                return JSONResponse({"detail": "Недопустимый источник запроса"}, status_code=403)
        if (request.method, request.url.path) not in OPEN_ROUTES and not authenticated(request):
            return JSONResponse({"detail": "нужен вход"}, status_code=401)
        return await call_next(request)

    app.add_middleware(SessionMiddleware, secret_key=secret_key, session_cookie="aidigest_session",
                       same_site="strict", https_only=secure_cookie, max_age=14 * 24 * 3600)

    @app.post("/api/login", status_code=204)
    async def login(body: LoginRequest, request: Request) -> Response:
        if not login_required:
            return Response(status_code=204)
        ip = client_ip(request, trust_real_ip=trust_real_ip)
        if limiter.blocked(ip):
            raise HTTPException(429, BLOCKED_TEXT)
        user_ok = hmac.compare_digest(body.username.encode("utf-8", "surrogatepass"),
                                      (username or "").encode("utf-8", "surrogatepass"))
        password_ok = hmac.compare_digest(body.password.encode("utf-8", "surrogatepass"),
                                          (password or "").encode("utf-8", "surrogatepass"))
        if username and user_ok and password_ok:
            limiter.reset(ip)
            request.session["auth"] = True
            return Response(status_code=204)
        limiter.failed(ip)
        raise HTTPException(401, "Неверный логин или пароль")

    @app.post("/api/logout", status_code=204)
    def logout(request: Request) -> Response:
        request.session.clear()
        return Response(status_code=204)

    @app.get("/api/me")
    def me(request: Request) -> SessionState:
        return SessionState(authenticated=authenticated(request), login_required=login_required)
