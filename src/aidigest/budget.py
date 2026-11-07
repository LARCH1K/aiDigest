"""Бюджет кредитов Tavily на один запуск: пул сбора и зарезервированный пул подтверждения."""
from typing import Literal

Pool = Literal["collect", "confirm"]


class BudgetExceeded(Exception):
    pass


class CreditBudget:
    def __init__(self, total: float, confirm_share: float = 0.4):
        self.total = total
        self._left = {"collect": total * (1 - confirm_share), "confirm": total * confirm_share}
        self.spent = 0.0

    def can_spend(self, pool: Pool, cost: float) -> bool:
        return self._left[pool] + 1e-9 >= cost

    def spend(self, pool: Pool, cost: float) -> None:
        if not self.can_spend(pool, cost):
            raise BudgetExceeded(f"пул «{pool}» исчерпан")
        self._left[pool] -= cost
        self.spent += cost

    def remaining(self, pool: Pool) -> float:
        return round(self._left[pool], 6)

    def close_collection(self) -> None:
        """Остаток сбора переходит в подтверждение (обратного переноса нет)."""
        self._left["confirm"] += self._left["collect"]
        self._left["collect"] = 0.0
