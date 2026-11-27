from base64 import b64encode
from datetime import date
from unittest.mock import Mock

import pytest

from aidigest.budget import CreditBudget
from aidigest.cache import DiskCache


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
    fetch = Mock(return_value="")
    monkeypatch.setattr("aidigest.yandex_search.fetch_article_text", fetch)
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
    monkeypatch.setattr("aidigest.yandex_search.fetch_article_text", lambda *_: "Описание кейса")
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
