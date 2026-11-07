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
