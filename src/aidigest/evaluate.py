"""Проверка качества извлечения на эталонных кейсах «Аналитики»."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel

from aidigest.cache import DiskCache
from aidigest.extract import extract_cases
from aidigest.fetch import fetch_text
from aidigest.llm import LLMClient, LLMFormatError
from aidigest.models import Article
from aidigest.quotes import extract_numbers
from aidigest.registry import SourceRegistry
from aidigest.urls import domain_of

_EPS = 1e-6


class ExpectedFigure(BaseModel):
    label: str
    numbers: list[float]


class ReferenceCase(BaseModel):
    id: str
    title: str
    urls: list[str]
    expected: list[ExpectedFigure]


@dataclass
class EvalResult:
    found: list[tuple[str, str]] = field(default_factory=list)
    missing: list[tuple[str, str]] = field(default_factory=list)
    unverified_metrics: int = 0
    empty_texts: list[str] = field(default_factory=list)
    unverified_examples: list[str] = field(default_factory=list)


def load_references(path: Path) -> list[ReferenceCase]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return [ReferenceCase(**r) for r in raw["references"]]


def fetch_all(refs: list[ReferenceCase], cache: DiskCache, manual_dir: Path) -> list[str]:
    """Скачивает тексты в кеш; возвращает URL, которые не удалось получить."""
    return [u for r in refs for i, u in enumerate(r.urls) if not fetch_text(u, cache, manual_dir, r.id, i)]


def run_eval(refs: list[ReferenceCase], llm: LLMClient, registry: SourceRegistry, cache: DiskCache,
             manual_dir: Path, today: date) -> EvalResult:
    res = EvalResult()
    for ref in refs:
        numbers: list[float] = []
        for i, url in enumerate(ref.urls):
            text = fetch_text(url, cache, manual_dir, ref.id, i, allow_network=False)
            if not text.strip():
                res.empty_texts.append(url)
                continue
            article = Article(url=url, domain=domain_of(url), title=ref.title, text=text)
            try:
                cases = extract_cases(article, llm, registry, today, 12000)
            except LLMFormatError as e:
                res.empty_texts.append(f"{url} (LLM: {e})")
                continue
            for c in cases:
                for m in c.metrics:
                    if m.quote_verified:
                        numbers += [n for p in (m.before, m.after, m.change) for n in extract_numbers(p)]
                    else:
                        res.unverified_metrics += 1
                        res.unverified_examples.append(f"{ref.id}: {m.name} | {m.before} → {m.after} "
                                                       f"({m.change}) | «{m.quote}»")
        for fig in ref.expected:
            ok = all(any(abs(n - x) <= _EPS + 1e-3 * abs(x) for x in numbers) for n in fig.numbers)
            (res.found if ok else res.missing).append((ref.id, fig.label))
    return res
