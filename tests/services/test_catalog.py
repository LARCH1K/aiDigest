"""Каталог запросов и источников: группировка и фильтры (config/*.yaml)."""
from pathlib import Path

from aidigest.config import load_queries
from aidigest.models import Level, Reliability
from aidigest.registry import SourceRegistry
from aidigest.services.catalog import ANY_RF_LABEL, ANY_RF_LEVEL, filter_sources, group_queries, level_label

CONFIG = Path(__file__).resolve().parents[2] / "config"


def sources():
    return SourceRegistry.load(CONFIG / "sources.yaml").sources


def test_group_queries_follows_level_order_and_covers_all():
    queries = load_queries(CONFIG / "queries.yaml")
    groups = group_queries(queries)
    levels = [lvl for lvl, _ in groups]
    assert levels == [lvl for lvl in Level if lvl in levels]
    assert sum(len(items) for _, items in groups) == len(queries)
    assert all(q.level == lvl for lvl, items in groups for q in items)


def test_filter_sources_without_filters_returns_all():
    assert len(filter_sources(sources())) == len(sources())


def test_filter_sources_by_reliability():
    out = filter_sources(sources(), reliability="высокая")
    assert out and all(s.reliability == Reliability.HIGH for s in out)
    assert "TAdviser" not in [s.name for s in out]


def test_filter_sources_by_level():
    world = [s for s in sources() if s.level is not None and s.level.value == "мир"]
    out = filter_sources(sources(), level="мир")
    assert len(out) == len(world) and all(s.level == Level.WORLD for s in out)


def test_filter_sources_any_rf_level():
    out = filter_sources(sources(), level=ANY_RF_LEVEL)
    assert all(s.level is None for s in out)


def test_level_label():
    assert level_label(None) == ANY_RF_LABEL
    assert level_label(Level.WORLD) == Level.WORLD.value
