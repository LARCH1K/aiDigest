"""Поиск статей через синхронный REST API Яндекса."""
import re
from base64 import b64decode
from datetime import date
from urllib.parse import urlsplit
from xml.etree import ElementTree

import requests

from aidigest.budget import CreditBudget, Pool
from aidigest.cache import DiskCache
from aidigest.fetch import fetch_article_text
from aidigest.models import Article
from aidigest.urls import domain_of, normalize_url

SEARCH_URL = "https://searchapi.api.cloud.yandex.net/v2/web/search"
MAX_QUERY_LENGTH = 400


def _matches_domain(domain: str, filters: list[str]) -> bool:
    return any(domain == allowed or domain.endswith("." + allowed) for allowed in filters)


def _xml_text(node: ElementTree.Element | None) -> str:
    return "".join(node.itertext()).strip() if node is not None else ""


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
        operators = []
        if include:
            operators.append("(" + " | ".join(f"site:{domain}" for domain in include) + ")")
        if start_date:
            operators.append(f"date:>={start_date.isoformat().replace('-', '')}")
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
            return [Article(url=row["url"], title=row["title"], domain=domain_of(row["url"]),
                            text=row["raw_content"] or row["content"])
                    for row in entry["results"]]
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
        articles = []
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
            full_text = fetch_article_text(url, self.cache)
            if full_text or snippet:
                results.append(dict(url=url, title=title, raw_content=full_text, content=snippet))
                articles.append(Article(url=url, domain=domain, title=title, text=full_text or snippet))
                if len(articles) == max_results:
                    break
        self.cache.put("yandex", cache_key, {"results": results})
        return articles
