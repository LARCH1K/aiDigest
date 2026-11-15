from aidigest.cli import main
from aidigest.usage import TavilyUsage


def test_run_refuses_when_tavily_says_exhausted(case_store, usage_says, capsys):
    usage_says(TavilyUsage(used=1000, limit=1000))
    assert main(["run", "--offline", "--budget", "5"]) == 2
    out = capsys.readouterr().out
    assert out.count("Причина:") == 1 and "Причина: Месячный лимит кредитов Tavily исчерпан" in out


def test_run_caps_budget_by_tavily_remaining(case_store, usage_says, capsys):
    usage_says(TavilyUsage(used=997, limit=1000))
    assert main(["run", "--offline", "--budget", "30"]) == 0
    out = capsys.readouterr().out
    assert "по данным Tavily: 997 из 1000" in out and "3 вместо 30" in out


def test_run_with_unknown_usage_uses_requested_budget(case_store, usage_says, capsys):
    usage_says(None)
    assert main(["run", "--offline", "--budget", "5"]) == 0
    out = capsys.readouterr().out
    assert "Расход кредитов Tavily неизвестен (сервис не ответил) — бюджет запуска 5." in out


def test_run_uses_first_run_budget_on_empty_base(case_store, usage_says, capsys):
    usage_says(None)
    assert main(["run", "--offline"]) == 0
    assert "бюджет запуска 100." in capsys.readouterr().out


def test_run_warns_when_usage_above_share(case_store, usage_says, capsys):
    usage_says(TavilyUsage(used=850, limit=1000))
    assert main(["run", "--offline", "--budget", "5"]) == 0
    assert "Внимание:" in capsys.readouterr().out


def test_run_report_has_no_own_credit_accounting(case_store, usage_says, capsys):
    usage_says(None)
    main(["run", "--offline", "--budget", "5"])
    out = capsys.readouterr().out
    assert "Кредитов Tavily за месяц" not in out and "Excel:" not in out
