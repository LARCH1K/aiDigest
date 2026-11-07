from datetime import date

from aidigest.usage import MonthlyUsage

NOV = date(2026, 11, 7)


def test_empty_file_means_nothing_spent(tmp_path):
    u = MonthlyUsage(tmp_path / "credits.json", limit=1000)
    assert u.spent(NOV) == 0 and u.remaining(NOV) == 1000


def test_record_accumulates_per_month(tmp_path):
    p = tmp_path / "credits.json"
    MonthlyUsage(p, 1000).record(NOV, 41)
    u = MonthlyUsage(p, 1000)
    u.record(NOV, 9.0)
    assert u.spent(NOV) == 50 and u.remaining(NOV) == 950
    assert u.spent(date(2026, 12, 1)) == 0


def test_cap_budget_by_monthly_remainder(tmp_path):
    u = MonthlyUsage(tmp_path / "c.json", 100)
    u.record(NOV, 90)
    assert u.cap(NOV, 30) == 10 and u.cap(NOV, 5) == 5
    u.record(NOV, 15)
    assert u.cap(NOV, 30) == 0


def test_warning_above_share(tmp_path):
    u = MonthlyUsage(tmp_path / "c.json", 1000, warn_share=0.8)
    u.record(NOV, 799)
    assert u.warning(NOV) is None
    u.record(NOV, 2)
    assert "801" in u.warning(NOV) and "1000" in u.warning(NOV)


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


def test_sync_raises_local_counter_only_up(tmp_path):
    u = MonthlyUsage(tmp_path / "c.json", 1000)
    u.record(NOV, 150)
    u.sync(NOV, 210)
    assert u.spent(NOV) == 210
    u.sync(NOV, 100)
    assert u.spent(NOV) == 210
