import pytest

from aidigest.cache import DiskCache
from aidigest.llm import LiteLLMClient, LLMFormatError, OfflineCacheMiss, parse_json_reply
from fakes import FakeOpenAI


def test_parse_fenced_and_prose():
    assert parse_json_reply('Вот ответ:\n```json\n{"cases": []}\n```') == {"cases": []}
    assert parse_json_reply('Результат: {"a": [1, 2]} конец') == {"a": [1, 2]}
    assert parse_json_reply('[{"x": "}"}]') == [{"x": "}"}]


def test_parse_garbage_raises():
    with pytest.raises(ValueError):
        parse_json_reply("никакого JSON тут нет")


def test_retry_once_then_success(tmp_path):
    fake = FakeOpenAI(["не json", '{"ok": true}'])
    llm = LiteLLMClient(None, None, "m", DiskCache(tmp_path), client=fake)
    assert llm.complete_json("s", "u") == {"ok": True} and llm.calls == 2
    assert fake.requests[0]["temperature"] == 0
    assert "только корректным JSON" in fake.requests[1]["messages"][-1]["content"]


def test_two_bad_replies_raise(tmp_path):
    llm = LiteLLMClient(None, None, "m", DiskCache(tmp_path), client=FakeOpenAI(["нет", "снова нет"]))
    with pytest.raises(LLMFormatError):
        llm.complete_json("s", "u")


def test_cache_hit_makes_no_call(tmp_path):
    cache = DiskCache(tmp_path)
    LiteLLMClient(None, None, "m", cache, client=FakeOpenAI(['{"x": 1}'])).complete_json("s", "u")
    again = LiteLLMClient(None, None, "m", cache, client=FakeOpenAI([]))
    assert again.complete_json("s", "u") == {"x": 1} and again.calls == 0


def test_offline_miss(tmp_path):
    llm = LiteLLMClient(None, None, "m", DiskCache(tmp_path), offline=True, client=FakeOpenAI([]))
    with pytest.raises(OfflineCacheMiss):
        llm.complete_json("s", "u")
