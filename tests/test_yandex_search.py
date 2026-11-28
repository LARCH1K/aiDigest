from base64 import b64encode
from datetime import date
from io import BytesIO
from unittest.mock import MagicMock, Mock

import pytest

from aidigest.budget import CreditBudget
from aidigest.cache import DiskCache
from aidigest.fetch import FetchedArticle


def test_yandex_search_cache_and_filters(tmp_path, monkeypatch):
    from aidigest.yandex_search import YandexSearch

    xml = """<yandexsearch><response><results><grouping><group>
      <doc><url>https://example.org/article</url><title>A <hlword>case</hlword></title>
      <passages><passage>Saved 25 minutes</passage></passages></doc>
      <doc><url>https://wrong.org/page</url><title>Wrong</title></doc>
    </group></grouping></results></response></yandexsearch>"""
    response = Mock()
    response.json.return_value = {"rawData": b64encode(xml.encode()).decode()}
    post = Mock(return_value=response)
    monkeypatch.setattr("aidigest.yandex_search.requests.post", post)
    fetch = Mock(return_value=FetchedArticle())
    monkeypatch.setattr("aidigest.yandex_search.fetch_article", fetch)
    cache = DiskCache(tmp_path)
    budget = CreditBudget(10, 0.3)
    client = YandexSearch("test-key", "folder", cache, budget)
    options = dict(pool="collect", include_domains=["example.org"], start_date=date(2026, 10, 1))
    articles = client.search("AI", **options)
    assert [(a.title, a.text, a.published_at) for a in articles] == [("A case", "Saved 25 minutes", None)]
    assert "date:>=20261001" in post.call_args.kwargs["json"]["query"]["queryText"]
    assert "site:example.org" in post.call_args.kwargs["json"]["query"]["queryText"]
    assert post.call_args.kwargs["json"]["query"]["searchType"] == "SEARCH_TYPE_COM"
    assert post.call_args.kwargs["json"]["folderId"] == "folder"
    offline = YandexSearch(None, None, cache, budget, offline=True)
    assert offline.search("AI", **options) == articles
    assert offline.search("other", **options) == []
    assert budget.spent == 1
    post.assert_called_once()
    fetch.assert_called_once()


@pytest.mark.parametrize(("metadata", "expected"), [
    ('<meta property="article:published_time" content="2026-10-03T23:40:00+05:00">'
     '<meta property="article:modified_time" content="2026-10-12">', "2026-10-03"),
    ('<script type="application/ld+json">{"@graph": [{"@type": "Article", '
     '"datePublished": "2026-10-03", "dateModified": "2026-10-12"}]}</script>', "2026-10-03"),
    ('<time itemprop="datePublished" datetime="2026-10-03">3 October 2026</time>', "2026-10-03"),
    ('<meta property="article:modified_time" content="2026-10-12">'
     '<script type="application/ld+json">{"dateModified": "2026-10-12"}</script>', None),
])
def test_yandex_keeps_only_original_date_from_downloaded_page(metadata, expected, tmp_path, monkeypatch):
    from urllib3.response import HTTPResponse

    from aidigest.yandex_search import YandexSearch

    xml = b"""<yandexsearch><response><results><doc><url>https://example.org/article</url>
      <title>Case</title><passages><passage>Search snippet</passage></passages>
      <modtime>2026-10-12</modtime></doc></results></response></yandexsearch>"""
    response = Mock()
    response.json.return_value = {"rawData": b64encode(xml).decode()}
    post = Mock(return_value=response)
    monkeypatch.setattr("aidigest.yandex_search.requests.post", post)
    monkeypatch.setattr("aidigest.fetch.getaddrinfo",
                        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))])
    body = f"""<!doctype html><html><head>{metadata}</head><body><article>
      <p>An AI pilot helped operators process requests faster and reduced the workload of the support team.
      The municipality shared the evaluation and published detailed metrics from three participating offices.</p>
      </article></body></html>""".encode()
    pool = MagicMock()
    pool.return_value.request.return_value = HTTPResponse(
        body=BytesIO(body), status=200, headers={"Last-Modified": "Mon, 12 Oct 2026 00:00:00 GMT"},
        preload_content=False,
    )
    monkeypatch.setattr("urllib3.HTTPSConnectionPool", pool)
    cache = DiskCache(tmp_path)
    budget = CreditBudget(10)
    articles = YandexSearch("key", "folder", cache, budget).search("AI", pool="collect")
    assert len(articles) == 1 and "reduced the workload" in articles[0].text
    assert articles[0].published_at == expected
    assert YandexSearch(None, None, cache, budget, offline=True).search("AI", pool="collect") == articles
    pool.return_value.request.assert_called_once()


def test_yandex_reads_results_cached_without_publication_metadata(tmp_path):
    from aidigest.publication import is_stale_publication
    from aidigest.yandex_search import YandexSearch

    cache = DiskCache(tmp_path)
    params = {
        "query": {"searchType": "SEARCH_TYPE_COM", "queryText": "AI date:>=20261024"},
        "groupSpec": {"groupMode": "GROUP_MODE_FLAT", "groupsOnPage": "5"},
        "responseFormat": "FORMAT_XML",
    }
    cache.put("yandex", {"params": params, "exclude": []}, {"results": [{
        "url": "https://example.org/2024/02/36414", "title": "Статья", "raw_content": "Текст", "content": "",
    }]})

    budget = CreditBudget(10)
    articles = YandexSearch(None, None, cache, budget, offline=True).search(
        "AI", pool="collect", start_date=date(2026, 10, 24),
    )
    assert len(articles) == 1 and articles[0].text == "Текст"
    assert articles[0].published_at is None
    assert is_stale_publication(articles[0], date(2026, 10, 24))
    assert budget.spent == 0


def test_xml_error_is_not_cached(tmp_path, monkeypatch):
    from aidigest.yandex_search import YandexSearch

    response = Mock()
    response.json.return_value = {"rawData": b64encode(
        b'<yandexsearch><response><error code="31"/></response></yandexsearch>'
    ).decode()}
    post = Mock(return_value=response)
    monkeypatch.setattr("aidigest.yandex_search.requests.post", post)
    budget = CreditBudget(10)
    client = YandexSearch("key", "folder", DiskCache(tmp_path), budget)
    for _ in range(2):
        with pytest.raises(ValueError, match="ошибку в XML"):
            client.search("ИИ", pool="collect")
    assert post.call_count == 2
    assert budget.spent == 2
    assert post.call_args.kwargs["json"]["query"]["searchType"] == "SEARCH_TYPE_RU"


def test_search_provider(monkeypatch):
    from aidigest.search import search_provider

    monkeypatch.delenv("AIDIGEST_SEARCH_PROVIDER", raising=False)
    assert search_provider() == "yandex"
    monkeypatch.setenv("AIDIGEST_SEARCH_PROVIDER", "tavily")
    assert search_provider() == "tavily"
    monkeypatch.setenv("AIDIGEST_SEARCH_PROVIDER", "other")
    with pytest.raises(ValueError):
        search_provider()


def test_search_splits_long_domain_list_without_dropping_domains(tmp_path, monkeypatch):
    from aidigest.yandex_search import YandexSearch

    domains = [f"public-ai-use-cases-{index:02}.example.org" for index in range(18)]
    response = Mock()
    response.json.return_value = {}
    post = Mock(return_value=response)
    monkeypatch.setattr("aidigest.yandex_search.requests.post", post)
    cache = DiskCache(tmp_path)
    budget = CreditBudget(10)
    client = YandexSearch("key", "folder", cache, budget)
    options = dict(pool="collect", include_domains=domains, start_date=date(2026, 10, 1))
    query = "government AI case studies"
    assert client.search(query, **options) == []
    texts = [call.kwargs["json"]["query"]["queryText"] for call in post.call_args_list]
    assert len(texts) > 1
    assert all(len(text) <= 400 and text.startswith(query) and "date:>=20261001" in text for text in texts)
    assert all(sum(f"site:{domain}" in text for text in texts) == 1 for domain in domains)
    assert budget.spent == len(texts)
    assert YandexSearch(None, None, cache, budget, offline=True).search(query, **options) == []
    assert post.call_count == len(texts)


def test_search_keeps_successful_group_when_another_group_fails(tmp_path, monkeypatch):
    from requests import ConnectionError

    from aidigest.yandex_search import YandexSearch

    domains = [f"public-ai-use-cases-{index:02}.example.org" for index in range(12)]
    url = f"https://{domains[0]}/project"
    xml = f"<yandexsearch><response><results><doc><url>{url}</url></doc></results></response></yandexsearch>"
    response = Mock()
    response.json.return_value = {"rawData": b64encode(xml.encode()).decode()}
    post = Mock(side_effect=[response, ConnectionError("вторая группа недоступна")])
    monkeypatch.setattr("aidigest.yandex_search.requests.post", post)
    monkeypatch.setattr("aidigest.yandex_search.fetch_article", lambda *_: FetchedArticle("Описание кейса"))
    client = YandexSearch("key", "folder", DiskCache(tmp_path), CreditBudget(10))
    articles = client.search("government AI case studies", pool="collect", include_domains=domains)
    assert [article.url for article in articles] == [url]
    assert post.call_count == 2


@pytest.mark.parametrize("payload", [{}, {"rawData": b64encode(
    b'<yandexsearch><response><error code="15"/></response></yandexsearch>'
).decode()}])
def test_empty_yandex_results_are_cached(payload, tmp_path, monkeypatch):
    from aidigest.yandex_search import YandexSearch

    response = Mock()
    response.json.return_value = payload
    post = Mock(return_value=response)
    monkeypatch.setattr("aidigest.yandex_search.requests.post", post)
    client = YandexSearch("key", "folder", DiskCache(tmp_path), CreditBudget(10))
    assert client.search("AI", pool="collect") == []
    assert client.search("AI", pool="collect") == []
    post.assert_called_once()
