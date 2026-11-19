"""Поиск статей через Tavily с учётом бюджета кредитов и дисковым кешем."""
from __future__ import annotations

import os
from datetime import date
from typing import Any, Literal, Protocol

from aidigest.budget import CreditBudget, Pool
from aidigest.cache import DiskCache
from aidigest.models import Article
from aidigest.urls import domain_of, normalize_url

CREDITS_PER_SEARCH = 1  # search_depth="basic"


def search_provider() -> Literal["yandex", "tavily"]:
    provider = os.environ.get("AIDIGEST_SEARCH_PROVIDER", "yandex").strip().lower()
    if provider in ("yandex", "tavily"):
        return provider
    raise ValueError("AIDIGEST_SEARCH_PROVIDER: недопустимое значение.")


class SearchClient(Protocol):
    def search(self, query: str, *, pool: Pool, include_domains: list[str] | None = None,
               exclude_domains: list[str] | None = None, start_date: date | None = None,
               max_results: int = 5) -> list[Article]: ...


class TavilySearch:
    def __init__(self, api_key: str | None, cache: DiskCache, budget: CreditBudget,
                 offline: bool = False, client: Any = None):
        self.cache = cache
        self.budget = budget
        self.offline = offline
        self.credits_spent = 0.0
        if client is None and not offline:
            from tavily import TavilyClient
            client = TavilyClient(api_key)
        self._client = client

    def search(self, query: str, *, pool: Pool, include_domains: list[str] | None = None,
               exclude_domains: list[str] | None = None, start_date: date | None = None,
               max_results: int = 5) -> list[Article]:
        params: dict[str, Any] = {
            "query": query, "search_depth": "basic", "topic": "general", "include_raw_content": "text",
            "max_results": max_results,
        }
        if include_domains:
            params["include_domains"] = include_domains
        if exclude_domains:
            params["exclude_domains"] = exclude_domains
        if start_date:
            params["start_date"] = start_date.isoformat()

        response = self.cache.get("tavily", params)
        if response is None:
            if self.offline:
                return []
            self.budget.spend(pool, CREDITS_PER_SEARCH)
            self.credits_spent += CREDITS_PER_SEARCH
            response = self._client.search(**params)
            self.cache.put("tavily", params, response)

        out = []
        for r in response.get("results", []):
            text = r.get("raw_content") or r.get("content") or ""
            if not text.strip() or not r.get("url"):
                continue
            out.append(Article(url=normalize_url(r["url"]), domain=domain_of(r["url"]),
                               title=r.get("title") or "", text=text, published_at=r.get("published_date")))
        return out
