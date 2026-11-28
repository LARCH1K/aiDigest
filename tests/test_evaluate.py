from datetime import date

from aidigest.cache import DiskCache
from aidigest.evaluate import ExpectedFigure, ReferenceCase, load_references, run_eval
from aidigest.fetch import fetch_text
from fakes import FakeLLM

TEXT = ("В Челябинской области ИИ анализирует дорожную обстановку. "
        "Время в пробках сократилось с 13 до 5 минут. Число ДТП снизилось со 161 до 122.")


def test_fetch_prefers_manual_text(tmp_path):
    (tmp_path / "ref-0.txt").write_text("ручной текст", encoding="utf-8")
    assert fetch_text("https://unreachable.invalid/x", DiskCache(tmp_path / "c"), tmp_path, "ref", 0) == "ручной текст"


def test_fetch_uses_cache_without_network(tmp_path):
    cache = DiskCache(tmp_path / "c")
    cache.put("fetch", "https://a.ru/1", "из кеша")
    assert fetch_text("https://a.ru/1", cache, tmp_path, "ref", 0) == "из кеша"


def test_run_eval_found_missing_unverified(tmp_path, registry, case_reply):
    (tmp_path / "chel-0.txt").write_text(TEXT, encoding="utf-8")
    ref = ReferenceCase(id="chel", title="Челябинск", urls=["https://gubernia74.ru/news/1"],
                        expected=[ExpectedFigure(label="пробки", numbers=[13, 5]),
                                  ExpectedFigure(label="ДТП", numbers=[161, 122])])
    reply = case_reply()  # пробки 13 → 5, цитата верная
    bad = dict(reply["cases"][0]["metrics"][0], name="ДТП", before="161", after="120",
               quote="Число ДТП снизилось со 161 до 122")
    reply["cases"][0]["metrics"].append(bad)
    res = run_eval([ref], FakeLLM([reply]), registry, DiskCache(tmp_path / "c"), tmp_path, date(2026, 11, 7))
    assert res.found == [("chel", "пробки")] and res.missing == [("chel", "ДТП")]
    assert res.unverified_metrics == 1 and res.empty_texts == []


def test_empty_text_is_reported_without_llm(tmp_path, registry):
    (tmp_path / "r-0.txt").write_text("", encoding="utf-8")
    ref = ReferenceCase(id="r", title="t", urls=["https://x.ru"], expected=[ExpectedFigure(label="a", numbers=[1])])
    llm = FakeLLM([])
    res = run_eval([ref], llm, registry, DiskCache(tmp_path / "c"), tmp_path, date(2026, 11, 7))
    assert res.empty_texts == ["https://x.ru"] and llm.calls == 0 and res.missing == [("r", "a")]


def test_real_reference_file_loads():
    from pathlib import Path
    refs = load_references(Path("eval/reference_cases.yaml"))
    assert {r.id for r in refs} == {"chelyabinsk-traffic", "belgorod-water", "tatarstan-gosprompt"}
