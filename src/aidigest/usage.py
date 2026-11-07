"""Учёт кредитов Tavily по месяцам (лимит тарифа — на месяц, бюджет запуска — на один запуск)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import requests

from aidigest.store import replace_with_retry


TAVILY_USAGE_URL = "https://api.tavily.com/usage"


@dataclass(frozen=True)
class TavilyUsage:
    """Фактический расход по данным самого Tavily (за их расчётный период, а не календарный месяц)."""
    used: float
    limit: float
    plan: str = ""

    @property
    def remaining(self) -> float:
        return max(0.0, self.limit - self.used)


def fetch_tavily_usage(token: str | None, timeout: float = 10) -> TavilyUsage | None:
    """GET /usage — бесплатный запрос. None, если ключа нет, сеть недоступна или ответ неожиданный."""
    if not token:
        return None
    try:
        r = requests.get(TAVILY_USAGE_URL, headers={"Authorization": f"Bearer {token}"}, timeout=timeout)
        if r.status_code != 200:
            return None
        d = r.json()
        account, key = d.get("account") or {}, d.get("key") or {}
        used = account.get("plan_usage", key.get("usage"))
        limit = account.get("plan_limit", key.get("limit"))
        if used is None or limit is None:
            return None
        return TavilyUsage(used=float(used), limit=float(limit), plan=str(account.get("current_plan") or ""))
    except Exception:
        return None


class MonthlyUsage:
    def __init__(self, path: Path, limit: float, warn_share: float = 0.8):
        self.path = Path(path)
        self.limit = limit
        self.warn_share = warn_share

    def _load(self) -> dict[str, float]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    @staticmethod
    def _month(day: date) -> str:
        return f"{day.year:04d}-{day.month:02d}"

    def spent(self, day: date) -> float:
        return float(self._load().get(self._month(day), 0))

    def remaining(self, day: date) -> float:
        return max(0.0, self.limit - self.spent(day))

    def cap(self, day: date, requested: float) -> float:
        """Бюджет запуска, урезанный до остатка месячного лимита."""
        return min(requested, self.remaining(day))

    def record(self, day: date, credits: float) -> None:
        data = self._load()
        key = self._month(day)
        data[key] = round(float(data.get(key, 0)) + credits, 6)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        replace_with_retry(tmp, self.path)

    def sync(self, day: date, actual: float) -> None:
        """Подтянуть локальный счётчик до фактического расхода (только вверх: расход не убывает)."""
        spent = self.spent(day)
        if actual > spent:
            self.record(day, actual - spent)

    def warning(self, day: date) -> str | None:
        spent = self.spent(day)
        if spent <= self.limit * self.warn_share:
            return None
        return (f"Внимание: в этом месяце потрачено {spent:g} кредитов Tavily из {self.limit:g} "
                f"(осталось {self.remaining(day):g}).")
