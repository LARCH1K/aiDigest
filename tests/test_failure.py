import errno
from types import SimpleNamespace

import requests

from aidigest.failure import explain, failure_reason
from aidigest.pipeline import RunReport


def test_explain_disk_full():
    assert "кончилось место" in explain(OSError(errno.ENOSPC, "x"))


def test_explain_auth():
    exc = type("HTTPError", (Exception,), {"status_code": 401})()
    assert "Tavily не принял ключ" in explain(exc, "Tavily")


def test_explain_auth_from_response():
    exc = Exception()
    exc.response = SimpleNamespace(status_code=403)
    assert explain(exc, "LiteLLM").startswith("LiteLLM не принял ключ")


def test_explain_tavily_invalid_key():
    from tavily.errors import InvalidAPIKeyError
    assert "Tavily не принял ключ" in explain(InvalidAPIKeyError("bad"), "Tavily")


def test_explain_network():
    assert "LiteLLM недоступен" in explain(requests.ConnectionError(), service="LiteLLM")


def test_explain_server_error_without_service():
    exc = Exception()
    exc.status_code = 502
    assert explain(exc).startswith("Внешний сервис недоступен")


def test_explain_unexpected():
    assert explain(ValueError("x")) == "Сбор: неожиданная ошибка (ValueError) — подробности в логе."


def test_failure_reason_all_searches_failed():
    reason = failure_reason(RunReport(searches_failed=3, last_search_error=requests.Timeout()))
    assert reason.startswith("Ни один поисковый запрос")
    assert "Поисковый сервис недоступен" in reason


def test_failure_reason_no_searches_is_ok():
    assert failure_reason(RunReport()) is None


def test_failure_reason_some_searches_ok():
    assert failure_reason(RunReport(searches_ok=1, searches_failed=2, last_search_error=requests.Timeout())) is None


def test_failure_reason_llm():
    reason = failure_reason(RunReport(searches_ok=1, articles_failed=2,
                                      last_llm_error=requests.ConnectionError()))
    assert reason.startswith("Ни одна статья")
    assert "LiteLLM недоступен" in reason
