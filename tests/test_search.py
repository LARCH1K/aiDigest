from datetime import date
from pathlib import Path

import pytest

from aidigest.budget import BudgetExceeded, CreditBudget
from aidigest.cache import DiskCache
from aidigest.config import load_queries, load_settings
from aidigest.models import Level
from aidigest.search import TavilySearch


class FakeTavily:
    def __init__(self):
        self.calls = []

    def search(self, **kw):
        self.calls.append(kw)
        return {"results": [
            {"url": "https://e1.ru/a?utm_source=t", "title": "T", "content": "c", "raw_content": "полный текст",
             "published_date": "2026-11-01"},
            {"url": "https://x.ru/empty", "title": "E", "content": "", "raw_content": None},
        ]}


def test_search_spends_one_credit_and_caches(tmp_path):
    b = CreditBudget(10)
    t = FakeTavily()
    s = TavilySearch(None, DiskCache(tmp_path), b, client=t)
    [a] = s.search("ИИ Екатеринбург", pool="collect", start_date=date(2026, 10, 8))
    assert a.url == "https://e1.ru/a" and a.text == "полный текст" and a.domain == "e1.ru"
    assert a.published_at == "2026-11-01"
    s.search("ИИ Екатеринбург", pool="collect", start_date=date(2026, 10, 8))
    assert len(t.calls) == 1 and b.spent == 1 and s.credits_spent == 1
    kw = t.calls[0]
    assert kw["search_depth"] == "basic" and kw["start_date"] == "2026-10-08" and kw["include_raw_content"] == "text"


def test_search_raises_when_pool_empty(tmp_path):
    s = TavilySearch(None, DiskCache(tmp_path), CreditBudget(1), client=FakeTavily())
    with pytest.raises(BudgetExceeded):
        s.search("q", pool="collect")


def test_offline_miss_returns_empty_without_call(tmp_path):
    t = FakeTavily()
    s = TavilySearch(None, DiskCache(tmp_path), CreditBudget(10), offline=True, client=t)
    assert s.search("q", pool="collect") == []
    assert t.calls == []


def test_real_configs_load():
    s = load_settings(Path("config/settings.yaml"))
    q = load_queries(Path("config/queries.yaml"))
    assert s.first_run_budget == 100 and s.run_budget == 30 and s.confirm_share == 0.4
    assert {x.level for x in q} == set(Level) and len(q) <= 14
    for lvl in Level:
        kinds = {x.use_registry_domains for x in q if x.level == lvl}
        assert kinds == {True, False}, lvl
