"""Загрузка ключей из env-файлов (litellm.env, tavily.env).

Содержимое файлов никогда не печатается и не логируется.
"""
from pathlib import Path


def load_env_file(path: Path) -> dict[str, str]:
    creds: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        creds[key.strip()] = value.strip().strip('"').strip("'")
    return creds
