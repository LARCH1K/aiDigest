"""Страницы «Запросы» и «Источники»: показывают config/queries.yaml и config/sources.yaml. Только чтение."""
from __future__ import annotations

from pathlib import Path

import yaml
from flask import Flask, current_app, render_template, request

from aidigest.config import QuerySpec, Settings, load_queries, load_settings
from aidigest.models import Level
from aidigest.registry import SourceInfo, SourceRegistry
from aidigest_web.views import RELIABILITY_ORDER, reliability_rank

# Источник без уровня (level: null) подходит обоим российским уровням — см. SourceRegistry.domains_for.
ANY_RF_LEVEL = "rf"
ANY_RF_LABEL = "регионы РФ и Свердловская область"

# Ошибки чтения конфига: нет файла, битый YAML, не те поля. Страница не должна падать с 500.
_CONFIG_ERRORS = (OSError, yaml.YAMLError, ValueError, KeyError, TypeError)


def _config_path(name: str) -> Path:
    return Path(current_app.config["CONFIG_DIR"]) / name


def level_label(level: Level | None) -> str:
    return level.value if level else ANY_RF_LABEL


def group_queries(queries: list[QuerySpec]) -> list[tuple[Level, list[QuerySpec]]]:
    """Запросы по уровням в порядке Level; пустые уровни пропускаются."""
    return [(lvl, [q for q in queries if q.level == lvl]) for lvl in Level if any(q.level == lvl for q in queries)]


def filter_sources(sources: list[SourceInfo], level: str = "", reliability: str = "") -> list[SourceInfo]:
    out = [s for s in sources
           if (not level or (s.level.value if s.level else ANY_RF_LEVEL) == level)
           and (not reliability or s.reliability.value == reliability)]
    levels = list(Level)
    return sorted(out, key=lambda s: (levels.index(s.level) if s.level else len(levels),
                                      reliability_rank(s.reliability), s.name.lower()))


def init(app: Flask) -> None:
    app.jinja_env.globals.update(level_label=level_label)

    @app.route("/queries")
    def queries():
        path = _config_path("queries.yaml")
        try:
            items, error = load_queries(path), None
        except _CONFIG_ERRORS as e:
            items, error = [], f"Не удалось прочитать {path.name}: {type(e).__name__}."
        try:
            freshness = load_settings(_config_path("settings.yaml")).freshness_days
        except _CONFIG_ERRORS:
            freshness = Settings().freshness_days
        return render_template("queries.html", groups=group_queries(items), total=len(items), error=error,
                               freshness_days=freshness)

    @app.route("/sources")
    def sources():
        path = _config_path("sources.yaml")
        try:
            items, error = SourceRegistry.load(path).sources, None
        except _CONFIG_ERRORS as e:
            items, error = [], f"Не удалось прочитать {path.name}: {type(e).__name__}."
        f = {"level": request.args.get("level", ""), "reliability": request.args.get("reliability", "")}
        level_options = [(lvl.value, lvl.value) for lvl in Level] + [(ANY_RF_LEVEL, ANY_RF_LABEL)]
        return render_template("sources.html", sources=filter_sources(items, **f), total=len(items), f=f,
                               error=error, level_options=level_options,
                               reliability_options=[r.value for r in RELIABILITY_ORDER])
