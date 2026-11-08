"""Загрузка ключей из env-файлов (litellm.env, tavily.env, web.env) и переменных окружения.

Содержимое файлов и значения ключей никогда не печатаются и не логируются.
"""
import os
from pathlib import Path

LITELLM_KEYS = ("LITELLM_API_KEY", "LITELLM_BASE_URL", "LITELLM_MODEL")
TAVILY_KEYS = ("TAVILY_TOKEN",)
WEB_KEYS = ("WEB_PASSWORD", "WEB_SECRET_KEY")


def load_env_file(path: Path) -> dict[str, str]:
    creds: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        creds[key.strip()] = value.strip().strip('"').strip("'")
    return creds


def load_creds(path: Path, keys: tuple[str, ...]) -> dict[str, str]:
    """Ключи из файла (если он есть), перекрытые непустыми переменными окружения.

    На сервере (Docker) ключи приходят переменными, локально — из файла.
    Пустые значения в результат не попадают.
    """
    creds = load_env_file(path) if Path(path).exists() else {}
    for key in keys:
        value = os.environ.get(key)
        if value:
            creds[key] = value
    return {k: v for k, v in creds.items() if v}
