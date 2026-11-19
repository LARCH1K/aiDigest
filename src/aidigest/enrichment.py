"""Дозаполнение архивных кейсов по сохранённым материалам."""
from __future__ import annotations

import sys
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date
from itertools import chain

from aidigest.cache import DiskCache
from aidigest.failure import explain
from aidigest.llm import LLMClient, OfflineCacheMiss
from aidigest.models import Article, Case
from aidigest.publication import case_update, publication_date
from aidigest.store import Store, StoreData
from aidigest.strategy import classify_strategy, strategy_input
from aidigest.urls import normalize_url


@dataclass
class EnrichmentReport:
    processed: int = 0
    saved: int = 0
    cache_misses: int = 0
    failed: int = 0


def _cached_articles(cache: DiskCache, urls: set[str]) -> dict[str, Article]:
    articles: dict[str, Article] = {}
    text_dates: dict[str, set[str]] = {}
    for response in chain(cache.values("tavily"), cache.values("yandex")):
        if not isinstance(response, dict) or not isinstance(response.get("results"), list):
            continue
        for row in response["results"]:
            if not isinstance(row, dict) or not isinstance(row.get("url"), str):
                continue
            try:
                url = normalize_url(row["url"])
            except ValueError:
                continue
            if url not in urls:
                continue
            raw_text = row.get("raw_content") or row.get("content")
            text = raw_text if isinstance(raw_text, str) and raw_text.strip() else ""
            value = row.get("published_date")
            published = publication_date(value) if isinstance(value, str) else None
            article = articles.setdefault(url, Article(url=url, domain="", title="", text=""))
            if len(text) > len(article.text):
                article.text = text
            # Метаданные публикации могут быть в другом кеше по тому же URL.
            article.published_at = article.published_at or published
            if not article.published_at and (text_date := publication_date(None, text)):
                text_dates.setdefault(url, set()).add(text_date)
    for url, dates in text_dates.items():
        if len(dates) == 1 and not articles[url].published_at:
            articles[url].published_at = dates.pop()
    return articles


def _case_articles(case: Case, cached: dict[str, Article], cache: DiskCache) -> list[Article]:
    articles = []
    for source in case.sources:
        key = normalize_url(source.url)
        article = cached.get(key)
        text = article.text if article else ""
        published = article.published_at if article else None
        if not text:
            try:
                fetched = cache.get("fetch", source.url)
            except (OSError, ValueError):
                fetched = None
            if isinstance(fetched, str):
                text = fetched
                published = published or publication_date(None, fetched)
        articles.append(Article(url=source.url, domain=source.domain, title=source.title, text=text,
                                published_at=published))
    return articles


def enrich_archive(store: Store, cache: DiskCache, llm: LLMClient, limit: int, today: date) -> EnrichmentReport:
    cases = sorted(store.load().cases, key=lambda case: case.id)
    report = EnrichmentReport()
    if not cases:
        return report
    try:
        cursor = cache.get("enrich", "last-case")
    except (OSError, ValueError):
        cursor = None
    # После последней записи возвращаемся к началу, чтобы повторить пропуски и ошибки.
    start = bisect_right(cases, cursor, key=lambda case: case.id) if isinstance(cursor, str) else 0
    urls = {normalize_url(source.url) for case in cases for source in case.sources}
    cached = _cached_articles(cache, urls)
    changed = []
    for case in cases[start:] + cases[:start]:
        articles = _case_articles(case, cached, cache)
        date_changes = [
            (source, article.published_at)
            for source, article in zip(case.sources, articles, strict=True)
            if not source.published_at and article.published_at
        ]
        signature = strategy_input(case, articles)
        classify = signature is not None and signature != case.strategy_input
        if not date_changes and not classify:
            continue

        before = case.model_copy(deep=True)
        with case_update(case, today):
            for source, published in date_changes:
                source.published_at = published
            if classify:
                try:
                    classify_strategy(case, llm, articles)
                except OfflineCacheMiss:
                    report.cache_misses += 1
                except Exception as exc:
                    report.failed += 1
                    print(f"Кейс {case.id}: {explain(exc, 'LiteLLM')}", file=sys.stderr)
        if case != before:
            changed.append(case)
        cursor = case.id
        report.processed += 1
        if report.processed >= limit:
            break

    if changed:
        store.save(StoreData(cases=changed))
        report.saved = len(changed)
    if report.processed:
        cache.put("enrich", "last-case", cursor)
    return report
