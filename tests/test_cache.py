from aidigest.cache import DiskCache


def test_cache_roundtrip_cyrillic(tmp_path):
    c = DiskCache(tmp_path)
    c.put("llm", {"q": "кейс"}, {"a": "ответ"})
    assert c.get("llm", {"q": "кейс"}) == {"a": "ответ"}
    assert c.get("llm", {"q": "другое"}) is None


def test_cache_survives_new_instance(tmp_path):
    DiskCache(tmp_path).put("tavily", "q", [1, 2])
    assert DiskCache(tmp_path).get("tavily", "q") == [1, 2]
