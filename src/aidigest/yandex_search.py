"""Поиск статей через синхронный REST API Яндекса."""
import logging
import re
from base64 import b64decode
from datetime import date
from itertools import zip_longest
from math import ceil
from urllib.parse import urlsplit
from xml.etree import ElementTree

import requests

from aidigest.budget import BudgetExceeded, CreditBudget, Pool
from aidigest.cache import DiskCache
from aidigest.fetch import fetch_article
from aidigest.models import Article
from aidigest.publication import publication_date
from aidigest.urls import domain_of, normalize_url

SEARCH_URL = "https://searchapi.api.cloud.yandex.net/v2/web/search"
MAX_QUERY_LENGTH = 400
_LOG = logging.getLogger(__name__)


def _matches_domain(domain: str, filters: list[str]) -> bool:
    return any(domain == allowed or domain.endswith("." + allowed) for allowed in filters)


def _xml_text(node: ElementTree.Element | None) -> str:
    return "".join(node.itertext()).strip() if node is not None else ""


def _article_from_result(row: dict) -> Article:
    return Article(url=row["url"], title=row["title"], domain=domain_of(row["url"]),
                   text=row["raw_content"] or row["content"], published_at=publication_date(row.get("published_date")))


def _domain_operator(domains: list[str]) -> str:
    return "(" + " | ".join(f"site:{domain}" for domain in domains) + ")"


def _domain_groups(domains: list[str], available: int) -> list[list[str]]:
    groups: list[list[str]] = [[]]
    for domain in domains:
        current = groups[-1]
        if current and len(_domain_operator([*current, domain])) > available:
            groups.append([domain])
        else:
            current.append(domain)
    return groups


class YandexSearch:
    def __init__(self, api_key: str | None, folder_id: str | None, cache: DiskCache,
                 budget: CreditBudget, offline: bool = False):
        self.api_key = api_key
        self.folder_id = folder_id
        self.cache = cache
        self.budget = budget
        self.offline = offline

    def search(self, query: str, *, pool: Pool, include_domains: list[str] | None = None,
               exclude_domains: list[str] | None = None, start_date: date | None = None,
               max_results: int = 5) -> list[Article]:
        if max_results <= 0:
            return []
        include = sorted({domain_of(f"https://{domain}") for domain in include_domains or []})
        exclude = sorted({domain_of(f"https://{domain}") for domain in exclude_domains or []})
        date_operator = f"date:>={start_date.isoformat().replace('-', '')}" if start_date else ""
        available = MAX_QUERY_LENGTH - len(query) - 1 - (len(date_operator) + 1 if date_operator else 0)
        groups = _domain_groups(include, available)
        if len(groups) == 1:
            return self._search(query, pool, groups[0], exclude, date_operator, max_results)

        batches = []
        last_error = None
        results_per_group = ceil(max_results / len(groups))
        for index, group in enumerate(groups, start=1):
            try:
                batches.append(self._search(query, pool, group, exclude, date_operator, results_per_group))
            except BudgetExceeded:
                if not batches:
                    raise
                _LOG.warning("Бюджет закончился до поиска по группе %d/%d доменов.", index, len(groups))
                break
            except (requests.RequestException, ValueError, ElementTree.ParseError) as exc:
                last_error = exc
                _LOG.warning("Не удалось выполнить поиск по группе %d/%d доменов (%s).",
                             index, len(groups), type(exc).__name__)
        if not batches and last_error is not None:
            raise last_error
        articles: dict[str, Article] = {}
        for row in zip_longest(*batches):
            for article in row:
                if article is not None:
                    articles.setdefault(article.url, article)
        return list(articles.values())[:max_results]

    def _search(self, query: str, pool: Pool, include: list[str], exclude: list[str],
                date_operator: str, max_results: int) -> list[Article]:
        operators = []
        if include:
            operators.append(_domain_operator(include))
        if date_operator:
            operators.append(date_operator)
        remaining = MAX_QUERY_LENGTH - sum(len(operator) + 1 for operator in operators)
        if remaining <= 0:
            raise ValueError("Ограничения по доменам превышают допустимую длину поиска.")
        search_type = "SEARCH_TYPE_RU" if re.search(r"[а-яё]", query, re.IGNORECASE) else "SEARCH_TYPE_COM"
        query = query[:remaining].rstrip()
        remaining -= len(query)
        for domain in exclude:
            operator = f"-site:{domain}"
            if len(operator) + 1 <= remaining:
                operators.append(operator)
                remaining -= len(operator) + 1
        params = {
            "query": {"searchType": search_type, "queryText": " ".join([query, *operators])},
            "groupSpec": {"groupMode": "GROUP_MODE_FLAT", "groupsOnPage": str(min(max_results, 100))},
            "responseFormat": "FORMAT_XML",
        }
        cache_key = {"params": params, "exclude": exclude}
        entry = self.cache.get("yandex", cache_key)
        if entry is not None:
            return [_article_from_result(row) for row in entry["results"]]
        if self.offline:
            return []

        self.budget.spend(pool, 1)
        response = requests.post(
            SEARCH_URL, json={**params, "folderId": self.folder_id},
            headers={"Authorization": f"Api-Key {self.api_key}"},
            timeout=20, allow_redirects=False,
        )
        response.raise_for_status()
        raw_data = response.json().get("rawData")
        if raw_data is None or raw_data == "":
            self.cache.put("yandex", cache_key, {"results": []})
            return []
        root = ElementTree.fromstring(b64decode(raw_data, validate=True))
        result = root.find("response")
        if result is None:
            raise ValueError("В ответе поискового сервиса отсутствует раздел результатов.")
        error = result.find("error")
        if error is not None:
            code = error.get("code")
            if code != "15":
                suffix = f" (код {code})" if code and code.isdecimal() else ""
                raise ValueError(f"Поисковый сервис вернул ошибку в XML{suffix}.")
            self.cache.put("yandex", cache_key, {"results": []})
            return []

        results = []
        seen = set()
        for doc in result.findall("./results//doc"):
            raw_url = _xml_text(doc.find("url"))
            try:
                parsed = urlsplit(raw_url)
                if parsed.scheme not in ("http", "https") or parsed.username is not None:
                    continue
                url = normalize_url(raw_url)
                domain = domain_of(url)
            except ValueError:
                continue
            if not domain or url in seen or (include and not _matches_domain(domain, include)):
                continue
            if _matches_domain(domain, exclude):
                continue
            seen.add(url)
            title = _xml_text(doc.find("title"))
            snippet = " ".join(filter(None, map(_xml_text, doc.findall("./passages/passage"))))
            fetched = fetch_article(url, self.cache)
            if fetched.text or snippet:
                results.append(dict(url=url, title=title, raw_content=fetched.text, content=snippet,
                                    published_date=fetched.published_at))
                if len(results) == max_results:
                    break
        self.cache.put("yandex", cache_key, {"results": results})
        return [_article_from_result(row) for row in results]
