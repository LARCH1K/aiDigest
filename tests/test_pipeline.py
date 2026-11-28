from datetime import date
from pathlib import Path

import pytest

from aidigest.budget import CreditBudget
from aidigest.cli import main
from aidigest.config import QuerySpec, load_settings
from aidigest.confirm import CONFIRM_SYSTEM_PROMPT
from aidigest.llm import LLMFormatError
from aidigest.models import Article, Flag, Level
from aidigest.pipeline import Deps, run_cycle
from aidigest.store import MemoryStore
from fakes import FakeLLM, FakeSearch

ROOT = Path(__file__).resolve().parent.parent
A1 = Article(url="https://e1.ru/1", domain="e1.ru", title="",
             text="В Свердловской области ИИ анализирует дорожную обстановку. Время ожидания сократилось с 10 до 2 минут.")
A2 = Article(url="https://e1.ru/2", domain="e1.ru", title="", text="Общая новость без кейса.")


def deps(store, search, llm, budget, registry, queries):
    return Deps(search, llm, registry, store, queries,
                load_settings(ROOT / "config" / "settings.yaml"), budget)


def sverd_reply(case_reply):
    return case_reply(region="Свердловская область", quote="сократилось с 10 до 2 минут",
                      before="10 мин", after="2 мин",
                      implementation_quote="В Свердловской области ИИ анализирует дорожную обстановку")


def test_cycle_collects_dedups_and_reports(tmp_path, registry, case_reply, case_store):
    b = CreditBudget(30)
    s = FakeSearch(lambda **kw: [A1, A2], budget=b)

    def route(system, user):
        if system == CONFIRM_SYSTEM_PROMPT:
            return {"matches": []}
        if "без кейса" in user:
            return {"cases": []}
        return sverd_reply(case_reply)
    llm = FakeLLM(route)
    q = [QuerySpec(level=Level.SVERDLOVSK, text="ИИ Екатеринбург", use_registry_domains=False, language="ru")]
    r = run_cycle(deps(case_store, s, llm, b, registry, q), set(Level), date(2026, 11, 7))
    assert r.articles_processed == 2 and r.articles_rejected == 1 and r.cases_new == 1
    assert r.confirmations_done == 1 and r.credits_spent == 2
    data = case_store.load()
    assert data.cases[0].level == Level.SVERDLOVSK and data.processed_urls == {A1.url, A2.url}
    assert s.calls[0]["start_date"] == date(2026, 10, 8)

    r2 = run_cycle(deps(case_store, s, llm, CreditBudget(30), registry, q), set(Level), date(2026, 11, 8))
    assert r2.articles_processed == 0 and r2.cases_new == 0


def test_registry_domains_used_for_restricted_query(tmp_path, registry, case_store):
    b = CreditBudget(30)
    s = FakeSearch(lambda **kw: [], budget=b)
    q = [QuerySpec(level=Level.SVERDLOVSK, text="x", use_registry_domains=True, language="ru"),
         QuerySpec(level=Level.WORLD, text="y", use_registry_domains=True, language="en")]
    run_cycle(deps(case_store, s, FakeLLM([]), b, registry, q), {Level.SVERDLOVSK}, date(2026, 11, 7))
    assert len(s.calls) == 1 and "digital.midural.ru" in s.calls[0]["include_domains"]


def test_budget_exhausted_mid_collection(tmp_path, registry, case_reply, case_store):
    b = CreditBudget(1, confirm_share=0.0)
    s = FakeSearch(lambda **kw: [A1], budget=b)
    q = [QuerySpec(level=Level.SVERDLOVSK, text=t, use_registry_domains=False, language="ru") for t in ("a", "b")]
    llm = FakeLLM(lambda system, user: sverd_reply(case_reply))
    r = run_cycle(deps(case_store, s, llm, b, registry, q), set(Level), date(2026, 11, 7))
    assert r.budget_exhausted and r.cases_new == 1 and r.confirmations_deferred == 1
    assert Flag.CONFIRMATION_SKIPPED in case_store.load().cases[0].flags


def test_llm_format_error_skips_article_without_marking(tmp_path, registry, case_store):
    class Broken:
        calls = 0

        def complete_json(self, system, user, validate=None):
            raise LLMFormatError("битый")
    b = CreditBudget(30)
    s = FakeSearch(lambda **kw: [A1], budget=b)
    q = [QuerySpec(level=Level.WORLD, text="x", use_registry_domains=False, language="en")]
    r = run_cycle(deps(case_store, s, Broken(), b, registry, q), set(Level), date(2026, 11, 7))
    assert r.articles_failed == 1 and case_store.load().processed_urls == set()


def test_search_error_moves_to_next_query(tmp_path, registry, case_store):
    b = CreditBudget(30)

    def flaky(**kw):
        if kw["query"] == "bad":
            raise ConnectionError("сеть")
        return []
    s = FakeSearch(flaky, budget=b)
    q = [QuerySpec(level=Level.WORLD, text=t, use_registry_domains=False, language="en") for t in ("bad", "ok")]
    run_cycle(deps(case_store, s, FakeLLM([]), b, registry, q), set(Level), date(2026, 11, 7))
    assert [c["query"] for c in s.calls] == ["bad", "ok"]


def test_llm_api_error_skips_article_and_run_finishes(tmp_path, registry, case_store):
    class Down:
        calls = 0

        def complete_json(self, system, user, validate=None):
            raise ConnectionError("прокси недоступен")
    b = CreditBudget(30)
    s = FakeSearch(lambda **kw: [A1], budget=b)
    q = [QuerySpec(level=Level.WORLD, text="x", use_registry_domains=False, language="en")]
    r = run_cycle(deps(case_store, s, Down(), b, registry, q), set(Level), date(2026, 11, 7))
    assert r.articles_failed == 1 and case_store.load().processed_urls == set()


def test_rejected_candidates_are_counted(tmp_path, registry, case_reply, case_store):
    b = CreditBudget(30)
    s = FakeSearch(lambda **kw: [A1], budget=b)
    r = case_reply(country=None, region=None, organization=None)
    llm = FakeLLM(lambda system, user: {"matches": []} if system == CONFIRM_SYSTEM_PROMPT else r)
    q = [QuerySpec(level=Level.WORLD, text="x", use_registry_domains=False, language="en")]
    rep = run_cycle(deps(case_store, s, llm, b, registry, q), set(Level), date(2026, 11, 7))
    assert rep.candidates_rejected == 1 and rep.cases_new == 0 and rep.articles_rejected == 1
    assert rep.as_rows()["Кандидатов отсеяно (не конкретное внедрение)"] == 1


def test_cycle_reports_progress_to_stderr(tmp_path, registry, case_reply, capsys, case_store):
    b = CreditBudget(30)
    s = FakeSearch(lambda **kw: [A1, A2], budget=b)

    def route(system, user):
        if system == CONFIRM_SYSTEM_PROMPT:
            return {"matches": []}
        if "без кейса" in user:
            return {"cases": []}
        return sverd_reply(case_reply)
    q = [QuerySpec(level=Level.SVERDLOVSK, text="ИИ Екатеринбург", use_registry_domains=False, language="ru")]
    run_cycle(deps(case_store, s, FakeLLM(route), b, registry, q), set(Level), date(2026, 11, 7))
    err = capsys.readouterr().err
    assert "Поиск 1/1 [Свердловская область]: «ИИ Екатеринбург» — статей: 2, новых: 2" in err
    assert "Статья 1/2" in err and "Подтверждение: кейсов в очереди 1" in err


def test_budget_exhausted_first_query_is_not_failure(tmp_path, registry, case_store):
    from aidigest.failure import failure_reason
    b = CreditBudget(0, confirm_share=0.0)
    s = FakeSearch(lambda **kw: [A1], budget=b)
    q = [QuerySpec(level=Level.WORLD, text=t, use_registry_domains=False, language="en") for t in ("a", "b")]
    r = run_cycle(deps(case_store, s, FakeLLM([]), b, registry, q), set(Level), date(2026, 11, 7))
    assert r.budget_exhausted and r.searches_ok == 0 and r.searches_failed == 0
    assert failure_reason(r) is None


def test_cycle_counts_failed_searches(tmp_path, registry, case_store):
    import requests

    def down(**kw):
        raise requests.ConnectionError("сеть")
    b = CreditBudget(30)
    s = FakeSearch(down, budget=b)
    q = [QuerySpec(level=Level.WORLD, text=t, use_registry_domains=False, language="en") for t in ("a", "b")]
    r = run_cycle(deps(case_store, s, FakeLLM([]), b, registry, q), set(Level), date(2026, 11, 7))
    assert r.searches_failed == len(q) and r.searches_ok == 0
    assert isinstance(r.last_search_error, requests.ConnectionError)
    assert "searches_failed" not in str(r.as_rows())


def test_cycle_remembers_llm_error(tmp_path, registry, case_store):
    class Down:
        def complete_json(self, system, user, validate=None):
            raise ConnectionError("прокси недоступен")
    b = CreditBudget(30)
    s = FakeSearch(lambda **kw: [A1], budget=b)
    q = [QuerySpec(level=Level.WORLD, text="x", use_registry_domains=False, language="en")]
    r = run_cycle(deps(case_store, s, Down(), b, registry, q), set(Level), date(2026, 11, 7))
    assert r.searches_ok == 1 and isinstance(r.last_llm_error, ConnectionError)


def test_cli_run_prints_reason_on_crash(tmp_path, monkeypatch, capsys, case_store):
    import errno

    def crash(*a, **kw):
        raise OSError(errno.ENOSPC, "x")
    monkeypatch.setenv("AIDIGEST_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("aidigest.pipeline.run_cycle", crash)
    assert main(["run", "--offline", "--budget", "3"]) == 1
    out = capsys.readouterr().out
    assert out.count("Причина:") == 1 and "Причина: На сервере кончилось место" in out


def test_cli_run_prints_reason_when_all_searches_failed(tmp_path, monkeypatch, capsys, case_store):
    import requests

    from aidigest.pipeline import RunReport

    def failed(*a, **kw):
        return RunReport(searches_failed=2, last_search_error=requests.ConnectionError())
    monkeypatch.setenv("AIDIGEST_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("aidigest.pipeline.run_cycle", failed)
    assert main(["run", "--offline", "--budget", "3"]) == 1
    out = capsys.readouterr().out
    assert "Excel:" not in out
    assert out.strip().splitlines()[-1].startswith("Причина: Ни один поисковый запрос не выполнился. Поисковый сервис недоступен")


def test_offline_cache_miss_is_not_failure(tmp_path, registry, case_store):
    from aidigest.failure import failure_reason
    from aidigest.llm import OfflineCacheMiss

    class Offline:
        def complete_json(self, system, user, validate=None):
            raise OfflineCacheMiss("нет в кеше")
    b = CreditBudget(30)
    s = FakeSearch(lambda **kw: [A1], budget=b)
    q = [QuerySpec(level=Level.WORLD, text="x", use_registry_domains=False, language="en")]
    r = run_cycle(deps(case_store, s, Offline(), b, registry, q), set(Level), date(2026, 11, 7))
    assert r.articles_failed == 1 and r.last_llm_error is None
    assert failure_reason(r) is None


def test_cli_run_prints_reason_when_keys_missing(tmp_path, monkeypatch, capsys, case_store):
    import aidigest.cli as cli
    monkeypatch.setenv("AIDIGEST_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "load_creds", lambda path, keys: {})
    assert main(["run", "--budget", "3"]) == 1
    out = capsys.readouterr().out
    assert out.count("Причина:") == 1 and "Причина: Не заданы настройки доступа к поиску" in out


def test_confirmations_saved_one_by_one(registry, case_reply, case_store):
    """Подтверждение второго кейса падает (KeyboardInterrupt) — результат первого уже в базе."""
    from aidigest.dedup import DEDUP_SYSTEM_PROMPT
    b = CreditBudget(30)
    evidence = "В Свердловской области ИИ помогает больницам выявлять опухоли"
    second_quote = "Число просмотренных снимков дошло до 25"
    article = A1.model_copy(update={"text": f"{A1.text} {evidence}. {second_quote}."})

    def search(**kw):
        if kw["pool"] == "confirm":
            if sum(c["pool"] == "confirm" for c in s.calls) > 1:  # текущий вызов уже записан
                raise KeyboardInterrupt
            return []
        return [article]
    s = FakeSearch(search, budget=b)
    reply = sverd_reply(case_reply)
    second = dict(reply["cases"][0], title="ИИ для больниц", industry="здравоохранение", application="выявлять опухоли",
                  implementation_quote=evidence, metrics=[{"name": "число снимков", "after": "25", "quote": second_quote}])
    reply = {"cases": [reply["cases"][0], second]}

    def route(system, user):
        if system == CONFIRM_SYSTEM_PROMPT:
            return {"matches": []}
        if system == DEDUP_SYSTEM_PROMPT:
            return {"duplicate_id": None}
        return reply
    q = [QuerySpec(level=Level.SVERDLOVSK, text="x", use_registry_domains=False, language="ru")]
    with pytest.raises(KeyboardInterrupt):
        run_cycle(deps(case_store, s, FakeLLM(route), b, registry, q), set(Level), date(2026, 11, 7))
    attempts = [c.confirmation_attempts for c in case_store.load().cases]
    assert sorted(attempts) == [0, 1]
