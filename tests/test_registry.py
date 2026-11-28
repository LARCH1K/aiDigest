from datetime import date
from pathlib import Path

import pytest

from aidigest.models import Article, Level, Reliability, SourceType
from aidigest.publication import is_stale_publication
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


@pytest.mark.parametrize(("path", "expected"), [
    ("/news/2024/02/05/story", "2024-02-05"),
    ("/news/story-2024-02-05", "2024-02-05"),
    ("/2024/02/36414", None),
    ("/2024/02/15", None),
    ("/2024/02/31/story", None),
    ("/story?date=2024-02-05", None),
])
def test_source_only_displays_precise_url_date(r, path, expected):
    article = Article(url=f"https://example.org{path}", domain="example.org", title="Статья", text="")
    assert r.to_source(article).published_at == expected


@pytest.mark.parametrize(("path", "metadata", "body", "since", "stale"), [
    ("/2024/02/36414", None, "", date(2026, 10, 24), True),
    ("/2024/02/36414", None, "", date(2024, 2, 29), False),
    ("/2024/02/36414", None, "", date(2024, 3, 1), True),
    ("/news/2024/02/05/story", None, "", date(2024, 2, 6), True),
    ("/2024/02/36414", "2026-11-02T23:30:00+05:00", "", date(2026, 11, 2), False),
    ("/story", "2026-02-30", "", date(2026, 11, 2), False),
    ("/story?date=2024-02-05", None, "Опубликовано 2 ноября 2026 года", date(2026, 11, 3), True),
    ("/story?date=2024-02-05", None, "Дата обновления: 2024-02-05", date(2026, 11, 3), False),
])
def test_publication_filter_requires_evidence_that_article_is_older(path, metadata, body, since, stale):
    article = Article(url=f"https://example.org{path}", domain="example.org", title="Статья", text=body,
                      published_at=metadata)
    assert is_stale_publication(article, since) is stale
