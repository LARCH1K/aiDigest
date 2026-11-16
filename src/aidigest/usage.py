"""Фактический расход кредитов Tavily (GET /usage) — единственный источник правды о лимите."""
from __future__ import annotations

from dataclasses import dataclass

import requests


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
