# --- фактический расход по данным Tavily (GET /usage) ---
from aidigest.usage import TavilyUsage, fetch_tavily_usage


class FakeResp:
    def __init__(self, status, data):
        self.status_code, self._data = status, data

    def json(self):
        return self._data


def test_fetch_tavily_usage_reads_plan(monkeypatch):
    import aidigest.usage as usage
    seen = {}

    def fake_get(url, headers, timeout):
        seen["url"], seen["auth"] = url, headers["Authorization"]
        return FakeResp(200, {"key": {"usage": 189, "limit": 1000},
                              "account": {"plan_usage": 210, "plan_limit": 1000, "current_plan": "Researcher"}})
    monkeypatch.setattr(usage.requests, "get", fake_get)
    assert fetch_tavily_usage("tok") == TavilyUsage(used=210, limit=1000, plan="Researcher")
    assert seen == {"url": "https://api.tavily.com/usage", "auth": "Bearer tok"}


def test_fetch_tavily_usage_returns_none_on_error(monkeypatch):
    import aidigest.usage as usage
    monkeypatch.setattr(usage.requests, "get", lambda *a, **k: FakeResp(401, {"detail": {"error": "x"}}))
    assert fetch_tavily_usage("tok") is None

    def boom(*a, **k):
        raise OSError("нет сети")
    monkeypatch.setattr(usage.requests, "get", boom)
    assert fetch_tavily_usage("tok") is None
    assert fetch_tavily_usage(None) is None
