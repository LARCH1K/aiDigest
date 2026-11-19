from unittest.mock import Mock

import pytest

from aidigest.cli import main
from aidigest.usage import TavilyUsage


@pytest.fixture
def tavily_run(monkeypatch, tmp_path, case_store):
    monkeypatch.setenv("AIDIGEST_SEARCH_PROVIDER", "tavily")
    monkeypatch.setenv("AIDIGEST_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("aidigest.cli.load_creds", lambda path, keys: {"TAVILY_TOKEN": "test"})
    monkeypatch.setattr("aidigest.search.TavilySearch", Mock())
    monkeypatch.setattr("aidigest.cli._llm", Mock())
    from aidigest.pipeline import RunReport
    monkeypatch.setattr("aidigest.pipeline.run_cycle", Mock(return_value=RunReport()))


def test_run_refuses_when_tavily_says_exhausted(tavily_run, usage_says, capsys):
    usage_says(TavilyUsage(used=1000, limit=1000))
    assert main(["run", "--budget", "5"]) == 2
    out = capsys.readouterr().out
    assert "Причина: Месячный лимит поисковых запросов исчерпан" in out


def test_run_caps_budget_by_tavily_remaining(tavily_run, usage_says, capsys):
    usage_says(TavilyUsage(used=997, limit=1000))
    assert main(["run", "--budget", "30"]) == 0
    assert "3 вместо 30" in capsys.readouterr().out


def test_run_with_unknown_usage_uses_requested_budget(tavily_run, usage_says, capsys):
    usage_says(None)
    assert main(["run", "--budget", "5"]) == 0
    assert "бюджет запуска 5" in capsys.readouterr().out


def test_run_uses_first_run_budget_on_empty_base(tavily_run, usage_says, capsys):
    usage_says(None)
    assert main(["run"]) == 0
    assert "бюджет запуска 100" in capsys.readouterr().out


def test_run_warns_when_usage_above_share(tavily_run, usage_says, capsys):
    usage_says(TavilyUsage(used=850, limit=1000))
    assert main(["run", "--budget", "5"]) == 0
    assert "Внимание:" in capsys.readouterr().out


def test_default_run_loads_yandex_only(monkeypatch, tmp_path, case_store):
    from aidigest.pipeline import RunReport

    monkeypatch.delenv("AIDIGEST_SEARCH_PROVIDER", raising=False)
    monkeypatch.setenv("AIDIGEST_DATA_DIR", str(tmp_path))
    usage = Mock(side_effect=AssertionError("Вызван второй провайдер"))
    monkeypatch.setattr("aidigest.cli.fetch_tavily_usage", usage)
    creds = Mock(return_value={"YANDEX_SEARCH_API_KEY": "test", "YANDEX_SEARCH_FOLDER_ID": "folder"})
    monkeypatch.setattr("aidigest.cli.load_creds", creds)
    monkeypatch.setattr("aidigest.cli._llm", Mock())
    client = Mock()
    monkeypatch.setattr("aidigest.yandex_search.YandexSearch", client)
    monkeypatch.setattr("aidigest.pipeline.run_cycle", Mock(return_value=RunReport()))
    assert main(["run", "--budget", "5"]) == 0
    assert creds.call_args.args[0].name == "secrets.env"
    assert client.call_args.args[:2] == ("test", "folder")
    usage.assert_not_called()


def test_offline_tavily_run_skips_usage(tavily_run, monkeypatch):
    usage = Mock(side_effect=AssertionError("Офлайн-запуск обратился в сеть"))
    monkeypatch.setattr("aidigest.cli.fetch_tavily_usage", usage)
    assert main(["run", "--offline", "--budget", "0"]) == 0
    usage.assert_not_called()
