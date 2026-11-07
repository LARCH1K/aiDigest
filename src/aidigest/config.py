"""Загрузка настроек и поисковых запросов из config/*.yaml."""
from pathlib import Path

import yaml
from pydantic import BaseModel

from aidigest.models import Level


class Settings(BaseModel):
    run_budget: float = 30
    first_run_budget: float = 100
    confirm_share: float = 0.4
    freshness_days: int = 30
    max_results: int = 5
    confirm_max_results: int = 5
    article_max_chars: int = 12000
    recheck_after_days: int = 28
    max_rechecks: int = 2
    llm_model: str = "GigaChat-3-Pro"
    monthly_limit: float = 1000
    monthly_warn_share: float = 0.8


class QuerySpec(BaseModel):
    level: Level
    text: str
    use_registry_domains: bool = False
    language: str = "ru"


def _yaml(path: Path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def load_settings(path: Path) -> Settings:
    return Settings(**_yaml(path))


def load_queries(path: Path) -> list[QuerySpec]:
    return [QuerySpec(**q) for q in _yaml(path).get("queries", [])]
