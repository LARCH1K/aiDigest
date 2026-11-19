import pytest

from aidigest.creds import TAVILY_KEYS, load_creds, load_env_file


def test_load_env_file_parses_quotes_and_comments(tmp_path):
    p = tmp_path / "x.env"
    p.write_text('# c\nA="1"\nB=\'2\'\nbad\n', encoding="utf-8")
    assert load_env_file(p) == {"A": "1", "B": "2"}


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_env_file(tmp_path / "nope.env")


def test_load_creds_env_overrides_file(tmp_path, monkeypatch):
    p = tmp_path / "secrets.env"
    p.write_text("TAVILY_TOKEN=file\n", encoding="utf-8")
    monkeypatch.setenv("TAVILY_TOKEN", "env")
    assert load_creds(p, TAVILY_KEYS) == {"TAVILY_TOKEN": "env"}


def test_load_creds_without_file_uses_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TAVILY_TOKEN", "env")
    assert load_creds(tmp_path / "nope.env", TAVILY_KEYS) == {"TAVILY_TOKEN": "env"}


def test_load_creds_empty_env_does_not_override(tmp_path, monkeypatch):
    p = tmp_path / "secrets.env"
    p.write_text("TAVILY_TOKEN=file\n", encoding="utf-8")
    monkeypatch.setenv("TAVILY_TOKEN", "")
    assert load_creds(p, TAVILY_KEYS) == {"TAVILY_TOKEN": "file"}


def test_load_creds_nothing_gives_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("TAVILY_TOKEN", raising=False)
    assert load_creds(tmp_path / "nope.env", TAVILY_KEYS) == {}


def test_load_creds_reads_only_requested_fields(tmp_path, monkeypatch):
    monkeypatch.delenv("TAVILY_TOKEN", raising=False)
    path = tmp_path / "secrets.env"
    path.write_text("TAVILY_TOKEN=fixture\nWEB_SECRET_KEY=other-fixture\n", encoding="utf-8-sig")
    assert load_creds(path, TAVILY_KEYS) == {"TAVILY_TOKEN": "fixture"}
