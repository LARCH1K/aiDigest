"""Каталог запросов и источников (config/queries.yaml, config/sources.yaml): группировка и фильтры. Без HTTP."""
from __future__ import annotations

import yaml

from aidigest.config import QuerySpec
from aidigest.models import Level
from aidigest.registry import SourceInfo, SourceRegistry
from aidigest.services.cases import RELIABILITY_ORDER, reliability_rank

# Источник без уровня (level: null) подходит обоим российским уровням — см. SourceRegistry.domains_for.
ANY_RF_LEVEL = "rf"
ANY_RF_LABEL = "регионы РФ и Свердловская область"

# Ошибки чтения конфига: нет файла, битый YAML, не те поля. Страница не должна падать с 500.
CONFIG_ERRORS = (OSError, yaml.YAMLError, ValueError, KeyError, TypeError)


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
