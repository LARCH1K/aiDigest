import pytest

from aidigest.budget import BudgetExceeded, CreditBudget


def test_budget_pools():
    b = CreditBudget(30)
    assert b.remaining("collect") == 18 and b.remaining("confirm") == 12
    for _ in range(18):
        b.spend("collect", 1)
    with pytest.raises(BudgetExceeded):
        b.spend("collect", 1)
    b.close_collection()
    assert b.remaining("confirm") == 12 and b.spent == 18


def test_budget_leftover_collect_moves_to_confirm():
    b = CreditBudget(10)
    b.spend("collect", 2)
    b.close_collection()
    assert b.remaining("confirm") == 8


def test_confirm_pool_never_feeds_collection():
    b = CreditBudget(10)
    for _ in range(6):
        b.spend("collect", 1)
    assert not b.can_spend("collect", 1) and b.can_spend("confirm", 4)
