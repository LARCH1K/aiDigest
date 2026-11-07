from pathlib import Path

import pytest

from aidigest.models import Article, Level, Reliability, SourceType
from aidigest.registry import SourceRegistry

REAL = Path("config/sources.yaml")


@pytest.fixture(scope="module")
def r():
    return SourceRegistry.load(REAL)


def test_real_registry_loads_and_covers_all_levels(r):
    for lvl in Level:
        assert r.domains_for(lvl), lvl


def test_lookup_cyrillic_punycode_and_parent(r):
    assert r.lookup("https://xn--80akpjgfht4a0d.xn--p1ai/x").reliability == Reliability.HIGH
    assert r.lookup("https://chel.kp.ru/daily/1").source_type == SourceType.MEDIA


def test_most_specific_domain_wins(r):
    assert r.lookup("https://digital.midural.ru/presscenter/news/13781/").name == "Минцифры Свердловской области"


def test_reuters_is_medium(r):
    assert r.lookup("https://www.reuters.com/technology/artificial-intelligence/x").reliability == Reliability.MEDIUM


def test_unknown_domain_becomes_unrated(r):
    s = r.to_source(Article(url="https://unknown-blog.ru/a", domain="unknown-blog.ru", title="t", text=""))
    assert s.reliability == Reliability.UNRATED and s.source_type == SourceType.UNKNOWN


def test_levelless_sources_go_to_russian_levels_only(r):
    assert "kp.ru" in r.domains_for(Level.SVERDLOVSK)
    assert "kp.ru" in r.domains_for(Level.RF_REGIONS)
    assert "kp.ru" not in r.domains_for(Level.WORLD)
