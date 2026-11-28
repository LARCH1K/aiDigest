"""Справочник источников: достоверность и тип по домену."""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from aidigest.models import Article, Level, Reliability, Source, SourceType
from aidigest.publication import article_publication_date
from aidigest.urls import domain_of, normalize_url

_RUSSIAN_LEVELS = {Level.RF_REGIONS, Level.SVERDLOVSK}


class SourceInfo(BaseModel):
    name: str
    domains: list[str]
    urls: list[str] = Field(default_factory=list)
    level: Level | None = None  # None — общероссийский источник, годится для уровней РФ
    reliability: Reliability
    source_type: SourceType
    update_frequency: str = ""


class SourceRegistry:
    def __init__(self, sources: list[SourceInfo]):
        self.sources = sources
        self._by_domain = {d.lower(): s for s in sources for d in s.domains}

    @classmethod
    def load(cls, path: Path) -> SourceRegistry:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls([SourceInfo(**item) for item in raw["sources"]])

    def lookup(self, url: str) -> SourceInfo | None:
        """Самое точное совпадение: сначала полный домен, потом родительские."""
        parts = domain_of(url).split(".")
        for i in range(len(parts) - 1):
            hit = self._by_domain.get(".".join(parts[i:]))
            if hit:
                return hit
        return None

    def domains_for(self, level: Level) -> list[str]:
        out = []
        for s in self.sources:
            if s.level == level or (s.level is None and level in _RUSSIAN_LEVELS):
                out.extend(s.domains)
        return out

    def to_source(self, article: Article) -> Source:
        info = self.lookup(article.url)
        return Source(
            url=normalize_url(article.url),
            domain=domain_of(article.url),
            title=article.title,
            published_at=article_publication_date(article),
            reliability=info.reliability if info else Reliability.UNRATED,
            source_type=info.source_type if info else SourceType.UNKNOWN,
        )
