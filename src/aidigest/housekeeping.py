"""Обслуживание папки данных: очистка старого кеша и выгрузок.

Вызывается только сборщиком на сервере (worker); локальный `aidigest run` ничего не чистит.
"""
from __future__ import annotations

from pathlib import Path

# Срок жизни кеша по пространствам имён, в днях. Поиск Tavily устаревает быстро (новые статьи),
# ответы LLM и тексты статей при тех же входных данных не меняются.
CACHE_MAX_AGE_DAYS = {"tavily": 14, "llm": 180, "fetch": 180}
DAY_SECONDS = 86400


def prune_older_than(dir: Path, max_age_days: int, now: float) -> int:
    """Удаляет файлы папки, изменённые раньше чем max_age_days дней назад; возвращает их число."""
    dir = Path(dir)
    if not dir.is_dir():
        return 0
    limit = now - max_age_days * DAY_SECONDS
    removed = 0
    for path in dir.iterdir():
        try:
            if path.is_file() and path.stat().st_mtime < limit:
                path.unlink()
                removed += 1
        except FileNotFoundError:
            continue  # файл уже удалили
    return removed


def keep_newest(dir: Path, pattern: str, n: int) -> int:
    """Оставляет n последних по имени файлов, подходящих под pattern; возвращает число удалённых."""
    dir = Path(dir)
    if not dir.is_dir():
        return 0
    files = sorted(p for p in dir.glob(pattern) if p.is_file())
    old = files[:-n] if n > 0 else files
    for path in old:
        path.unlink(missing_ok=True)
    return len(old)


def prune_cache(data_dir: Path, now: float) -> int:
    """Чистит <data>/cache по срокам CACHE_MAX_AGE_DAYS; возвращает число удалённых файлов."""
    cache = Path(data_dir) / "cache"
    return sum(prune_older_than(cache / ns, days, now) for ns, days in CACHE_MAX_AGE_DAYS.items())
