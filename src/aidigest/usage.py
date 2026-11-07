"""Учёт кредитов Tavily по месяцам (лимит тарифа — на месяц, бюджет запуска — на один запуск)."""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path


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
        os.replace(tmp, self.path)

    def warning(self, day: date) -> str | None:
        spent = self.spent(day)
        if spent <= self.limit * self.warn_share:
            return None
        return (f"Внимание: в этом месяце потрачено {spent:g} кредитов Tavily из {self.limit:g} "
                f"(осталось {self.remaining(day):g}).")
