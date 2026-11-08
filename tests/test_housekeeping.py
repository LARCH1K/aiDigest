import os
import time
from datetime import datetime, timedelta

from aidigest import housekeeping as hk

DAY = 86400


def _file(path, age_days, now):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    os.utime(path, (now - age_days * DAY, now - age_days * DAY))
    return path


def test_prune_cache_by_namespace(tmp_path):
    now = time.time()
    old = _file(tmp_path / "cache" / "tavily" / "old.json", 15, now)
    fresh = _file(tmp_path / "cache" / "tavily" / "fresh.json", 13, now)
    llm = _file(tmp_path / "cache" / "llm" / "a.json", 100, now)
    assert hk.prune_cache(tmp_path, now) == 1
    assert not old.exists()
    assert fresh.exists() and llm.exists()


def test_prune_cache_without_cache_dir(tmp_path):
    assert hk.prune_cache(tmp_path, time.time()) == 0


def test_keep_newest(tmp_path):
    for day in range(1, 36):
        (tmp_path / f"cases_2026-10-{day:02d}.xlsx").write_text("x", encoding="utf-8")
    (tmp_path / "note.txt").write_text("x", encoding="utf-8")
    assert hk.keep_newest(tmp_path, "*.xlsx", 30) == 5
    left = sorted(p.name for p in tmp_path.glob("*.xlsx"))
    assert len(left) == 30
    assert left[0] == "cases_2026-10-06.xlsx"
    assert (tmp_path / "note.txt").exists()


def test_backup_cases_keeps_30(tmp_path):
    (tmp_path / "cases.json").write_text('{"cases": []}', encoding="utf-8")
    start = datetime(2026, 11, 8, 12, 0, 0)
    for i in range(32):
        last = hk.backup_cases(tmp_path, start + timedelta(minutes=i))
    backups = sorted(p.name for p in (tmp_path / "backups").iterdir())
    assert len(backups) == 30
    assert backups[-1] == "cases_2026-11-08_123100.json"
    assert last == tmp_path / "backups" / "cases_2026-11-08_123100.json"
    assert last.read_text(encoding="utf-8") == '{"cases": []}'


def test_backup_without_base_returns_none(tmp_path):
    assert hk.backup_cases(tmp_path, datetime(2026, 11, 8)) is None
    assert not (tmp_path / "backups").exists()
