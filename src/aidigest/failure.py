"""Короткая понятная причина неудачного сбора — для строки «Причина: …» в выводе aidigest run."""
from __future__ import annotations

import builtins
import errno
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aidigest.pipeline import RunReport


def _classes(module: str, *names: str) -> tuple[type, ...]:
    """Классы исключений из необязательного модуля; отсутствующие имена пропускаются."""
    try:
        mod = __import__(module, fromlist=list(names))
    except ImportError:
        return ()
    return tuple(c for c in (getattr(mod, n, None) for n in names) if isinstance(c, type))


def _status_code(exc: BaseException) -> int | None:
    code = getattr(exc, "status_code", None)
    if code is None:
        code = getattr(getattr(exc, "response", None), "status_code", None)
    return code if isinstance(code, int) else None


def _auth_classes() -> tuple[type, ...]:
    return (_classes("openai", "AuthenticationError", "PermissionDeniedError")
            + _classes("tavily.errors", "InvalidAPIKeyError", "ForbiddenError"))


def _network_classes() -> tuple[type, ...]:
    return ((builtins.ConnectionError, builtins.TimeoutError)
            + _classes("requests", "ConnectionError", "Timeout")
            + _classes("openai", "APIConnectionError", "APITimeoutError", "InternalServerError")
            + _classes("tavily.errors", "TimeoutError"))


def explain(exc: BaseException, service: str | None = None) -> str:
    """Причина ошибки одной фразой; service — «Tavily» или «LiteLLM»."""
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return "На сервере кончилось место на диске."
    name = service or "Внешний сервис"
    code = _status_code(exc)
    if code in (401, 403) or isinstance(exc, _auth_classes()):
        return f"{name} не принял ключ — проверьте ключ на сервере."
    if (code is not None and code >= 500) or isinstance(exc, _network_classes()):
        return f"{name} недоступен (сеть или сбой сервиса) — попробуйте позже."
    return f"{service or 'Сбор'}: неожиданная ошибка ({type(exc).__name__}) — подробности в логе."


def failure_reason(report: RunReport) -> str | None:
    """Причина, по которой завершившийся сбор всё равно считается неудачным; None — сбор удался."""
    if report.searches_ok == 0 and report.searches_failed > 0:
        return "Ни один поисковый запрос не выполнился. " + explain(report.last_search_error, "Поисковый сервис")
    # last_llm_error не задан, если статьи «упали» только из-за промаха офлайн-кеша — это не сбой.
    if report.articles_processed == 0 and report.articles_failed > 0 and report.last_llm_error is not None:
        return "Ни одна статья не обработана. " + explain(report.last_llm_error, "LiteLLM")
    return None
