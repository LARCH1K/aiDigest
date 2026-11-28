from contextlib import contextmanager
from datetime import date

import pytest

from aidigest.cache import DiskCache
from aidigest.cli import main
from aidigest.llm import OfflineCacheMiss
from aidigest.store import StoreData


class ArchiveLLM:
    def __init__(self):
        self.calls = 0
        self.cache_miss = False

    def complete_json(self, system, user, validate):
        self.calls += 1
        if self.cache_miss:
            raise OfflineCacheMiss("нет ответа в кеше")
        return validate({"links": []})


@pytest.fixture
def archive(tmp_path_factory, monkeypatch, case_store):
    data_dir = tmp_path_factory.mktemp("archive")
    cache = DiskCache(data_dir / "cache")
    llm = ArchiveLLM()
    monkeypatch.setenv("AIDIGEST_DATA_DIR", str(data_dir))
    monkeypatch.setattr("aidigest.cli._llm", lambda settings, actual_cache, offline: llm)

    def forbidden(*args, **kwargs):
        pytest.fail("Архивное дозаполнение вызвало Tavily")

    monkeypatch.setattr("aidigest.cli.fetch_tavily_usage", forbidden)
    monkeypatch.setattr("aidigest.search.TavilySearch", forbidden)
    return case_store, cache, llm


@pytest.mark.parametrize("namespace", ["tavily", "yandex"])
def test_archive_continues_after_unavailable_cases_and_skips_completed(archive, make_case, make_source, namespace):
    store, cache, llm = archive
    url = "https://example.org/first"
    store.save(StoreData([
        make_case(id="a", sources=[], metrics=[]),
        make_case(id="b", sources=[make_source(url)], metrics=[]),
        make_case(id="c"),
    ], {"https://processed.example.org"}))
    cache.put(namespace, {"query": "запрос"}, {"results": [{
        "url": url + "?utm_source=search",
        "raw_content": "Сотрудники прошли обучение работе с искусственным интеллектом.",
        "published_date": "2025-02-03T13:14:00+03:00",
    }]})

    assert main(["enrich", "--limit", "1", "--offline"]) == 0
    cases = {c.id: c for c in store.load().cases}
    assert cases["a"].plan_input is None
    assert cases["b"].sources[0].published_at == "2025-02-03"
    assert cases["b"].updated == date.today()
    assert cases["b"].plan_input is not None
    assert cases["c"].plan_input is None
    assert llm.calls == 1

    assert main(["enrich", "--limit", "1", "--offline"]) == 0
    assert main(["enrich", "--limit", "1", "--offline"]) == 0
    after = store.load()
    assert llm.calls == 2
    assert after.cases[2].plan_input is not None
    assert after.cases[2].updated == date(2026, 11, 1)
    assert after.processed_urls == {"https://processed.example.org"}


def test_archive_retries_cache_miss_without_blocking_next_batch(archive, make_case, make_source):
    store, cache, llm = archive
    b_url = "https://example.org/b"
    store.save(StoreData([make_case(id="a"), make_case(id="b", metrics=[], sources=[
        make_source(b_url),
    ])]))
    cache.put("tavily", {"query": "дата"}, {"results": [{"url": b_url, "published_date": "2025-02-03T09:00:00Z"}]})
    llm.cache_miss = True
    assert main(["enrich", "--limit", "1", "--offline"]) == 0
    assert llm.calls == 1
    assert store.load().cases[0].plan_input is None

    assert main(["enrich", "--limit", "1", "--offline"]) == 0
    assert store.load().cases[1].sources[0].published_at == "2025-02-03"
    assert llm.calls == 1

    llm.cache_miss = False
    assert main(["enrich", "--limit", "1", "--offline"]) == 0
    assert llm.calls == 2
    assert store.load().cases[0].plan_input is not None


def test_archive_preserves_new_date_even_when_llm_cache_is_missing(archive, make_case, make_source):
    store, cache, llm = archive
    url = "https://example.org/training"
    store.save(StoreData([make_case(sources=[make_source(url)], metrics=[])]))
    cache.put("tavily", {"query": "один"}, {"results": [{"url": url, "content": "Опубликовано 03.02.2025"}]})
    cache.put("tavily", {"query": "два"}, {"results": [{
        "url": url,
        "raw_content": "Сотрудники прошли обучение работе с искусственным интеллектом.",
    }]})
    llm.cache_miss = True

    assert main(["enrich", "--limit", "1", "--offline"]) == 0
    case = store.load().cases[0]
    assert case.sources[0].published_at == "2025-02-03"
    assert case.updated == date.today()
    assert case.plan_input is None
    assert llm.calls == 1


@pytest.mark.parametrize("fetch_entry", [
    "Опубликовано 03.02.2025\nСотрудники прошли обучение работе с искусственным интеллектом.",
    {"text": "Сотрудники прошли обучение работе с искусственным интеллектом.",
     "published_date": "2025-02-03"},
])
def test_archive_reads_publication_date_in_old_and_new_http_cache(archive, make_case, make_source, fetch_entry):
    store, cache, _ = archive
    url = "https://example.org/training"
    store.save(StoreData([make_case(sources=[make_source(url)], metrics=[])]))
    cache.put("fetch", url, fetch_entry)

    assert main(["enrich", "--limit", "1", "--offline"]) == 0
    assert store.load().cases[0].sources[0].published_at == "2025-02-03"


@pytest.mark.parametrize("command", [["run", "--offline"], ["enrich", "--limit", "1", "--offline"]])
def test_commands_refuse_while_another_writer_holds_lock(case_store, monkeypatch, capsys, command):
    from aidigest.store import WriterBusy

    @contextmanager
    def locked():
        raise WriterBusy
        yield

    def forbidden():
        pytest.fail("Чтение базы началось до захвата блокировки")

    monkeypatch.setattr(case_store, "write_lock", locked)
    monkeypatch.setattr(case_store, "load", forbidden)
    assert main(command) == 1
    assert "уже выполняется" in capsys.readouterr().out
