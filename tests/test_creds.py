import pytest

from aidigest.creds import load_env_file


def test_load_env_file_parses_quotes_and_comments(tmp_path):
    p = tmp_path / "x.env"
    p.write_text('# c\nA="1"\nB=\'2\'\nbad\n', encoding="utf-8")
    assert load_env_file(p) == {"A": "1", "B": "2"}


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_env_file(tmp_path / "nope.env")
