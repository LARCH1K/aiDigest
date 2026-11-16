"""Консольные команды сбора, проверки и дозаполнения кейсов."""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from datetime import date
from pathlib import Path

from aidigest.budget import CreditBudget
from aidigest.cache import DiskCache
from aidigest.config import load_queries, load_settings
from aidigest.creds import LITELLM_KEYS, TAVILY_KEYS, load_creds
from aidigest.failure import explain, failure_reason
from aidigest.models import Level
from aidigest.registry import SourceRegistry
from aidigest.store import PgCaseStore, Store, WriterBusy
from aidigest.usage import fetch_tavily_usage

ROOT = Path(__file__).resolve().parents[2]


def _data_dir() -> Path:
    return Path(os.environ.get("AIDIGEST_DATA_DIR") or ROOT / "data")


_CRED_KEYS = {"litellm.env": LITELLM_KEYS, "tavily.env": TAVILY_KEYS}
_WRITER_BUSY = "Причина: Сбор или дозаполнение уже выполняется. Повторите после завершения."


class MissingCreds(SystemExit):
    """Нет ключей для онлайн-запуска; вне cmd_run ведёт себя как обычный SystemExit с сообщением."""


def _creds(name: str, offline: bool) -> dict[str, str]:
    creds = load_creds(ROOT / name, _CRED_KEYS[name])
    if not creds and not offline:
        raise MissingCreds(f"Не найдены ключи {name}: задайте файл в корне проекта или переменные окружения.")
    return creds


def _llm(settings, cache: DiskCache, offline: bool):
    from aidigest.llm import LiteLLMClient
    c = _creds("litellm.env", offline)
    return LiteLLMClient(c.get("LITELLM_API_KEY"), c.get("LITELLM_BASE_URL"),
                         c.get("LITELLM_MODEL") or settings.llm_model, cache, offline=offline)


def _parse_levels(raw: str | None) -> set[Level]:
    if not raw:
        return set(Level)
    return {Level(x.strip()) for x in raw.split(",") if x.strip()}


def _case_store() -> Store:
    from aidigest.db.engine import make_engine
    return PgCaseStore(make_engine())


def cmd_run(args) -> int:
    """Любой неудачный запуск печатает ровно одну строку «Причина: …» (её показывает веб-интерфейс).
    Коды выхода: 0 — успех, 1 — ошибка, 2 — месячный лимит кредитов исчерпан."""
    try:
        settings = load_settings(ROOT / "config" / "settings.yaml")
        if args.days:
            settings.freshness_days = args.days
        with _case_store().write_lock() as store:
            return _run_all(args, settings, store)
    except WriterBusy:
        print(_WRITER_BUSY)
        return 1
    except MissingCreds as e:
        print(f"Причина: {e}")
        return 1
    except Exception as e:
        traceback.print_exc()
        print(f"Причина: {explain(e)}")
        return 1


def _run_all(args, settings, store: Store) -> int:
    """Сбор целиком (включая сверку кредитов с Tavily)."""
    from aidigest.pipeline import Deps, run_cycle
    from aidigest.search import TavilySearch

    today = date.today()
    if args.budget is not None:
        requested = args.budget
    elif args.first_run or not store.load().cases:  # пустая база — бюджет первого запуска
        requested = settings.first_run_budget
    else:
        requested = settings.run_budget
    tavily = _creds("tavily.env", args.offline)
    # Единственный источник правды о расходе — сам Tavily (GET /usage).
    actual = fetch_tavily_usage(tavily.get("TAVILY_TOKEN"))
    if actual is None:
        print(f"Расход кредитов Tavily неизвестен (сервис не ответил) — бюджет запуска {requested:g}.")
        total = requested
    else:
        print(f"Кредиты по данным Tavily: {actual.used:g} из {actual.limit:g}.")
        if requested > 0 and actual.remaining <= 0:
            print("Причина: Месячный лимит кредитов Tavily исчерпан — новый сбор возможен после пополнения.")
            return 2
        total = min(requested, actual.remaining)
        if total < requested:
            print(f"Бюджет запуска урезан до остатка месячного лимита: {total:g} вместо {requested:g}.")
        if actual.used > actual.limit * settings.monthly_warn_share:
            print(f"Внимание: в этом месяце потрачено {actual.used:g} кредитов Tavily из {actual.limit:g} "
                  f"(осталось {actual.remaining:g}).")
    budget = CreditBudget(total, settings.confirm_share)
    cache = DiskCache(_data_dir() / "cache")
    deps = Deps(
        search=TavilySearch(tavily.get("TAVILY_TOKEN"), cache, budget, offline=args.offline),
        llm=_llm(settings, cache, args.offline),
        registry=SourceRegistry.load(ROOT / "config" / "sources.yaml"),
        store=store,
        queries=load_queries(ROOT / "config" / "queries.yaml"),
        settings=settings, budget=budget,
    )
    report = run_cycle(deps, _parse_levels(args.levels), today)
    for k, v in report.as_rows().items():
        print(f"{k}: {v}")
    reason = failure_reason(report)
    if reason is not None:
        print(f"Причина: {reason}")
        return 1
    return 0


def cmd_enrich(args) -> int:
    from aidigest.enrichment import enrich_archive

    try:
        with _case_store().write_lock() as store:
            settings = load_settings(ROOT / "config" / "settings.yaml")
            cache = DiskCache(_data_dir() / "cache")
            llm = _llm(settings, cache, args.offline)
            report = enrich_archive(store, cache, llm, args.limit, date.today())
    except WriterBusy:
        print(_WRITER_BUSY)
        return 1
    except MissingCreds as e:
        print(f"Причина: {e}")
        return 1
    print(f"Кейсов обработано: {report.processed}")
    print(f"Кейсов сохранено: {report.saved}")
    print(f"Нет ответа в кеше LiteLLM: {report.cache_misses}")
    print(f"Кейсов с ошибкой LiteLLM: {report.failed}")
    print(f"Вызовов LLM: {llm.calls}")
    return int(report.failed > 0)


def _positive_int(raw: str) -> int:
    value = int(raw)
    if value < 1:
        raise argparse.ArgumentTypeError("лимит должен быть не меньше 1")
    return value


def cmd_eval(args) -> int:
    from aidigest.evaluate import fetch_all, load_references, run_eval

    refs = load_references(ROOT / "eval" / "reference_cases.yaml")
    cache = DiskCache(_data_dir() / "cache")
    manual = ROOT / "eval" / "texts"
    if args.fetch_only:
        failed = fetch_all(refs, cache, manual)
        for u in failed:
            print(f"Не скачано: {u}")
        print(f"Скачано {sum(len(r.urls) for r in refs) - len(failed)} из {sum(len(r.urls) for r in refs)}")
        return 0
    settings = load_settings(ROOT / "config" / "settings.yaml")
    llm = _llm(settings, cache, args.offline)
    res = run_eval(refs, llm, SourceRegistry.load(ROOT / "config" / "sources.yaml"), cache, manual, date.today())
    for ref_id, label in res.found:
        print(f"[найдено]     {ref_id}: {label}")
    for ref_id, label in res.missing:
        print(f"[НЕ НАЙДЕНО]  {ref_id}: {label}")
    print(f"Непроверенных метрик (цитата/число не найдены в тексте): {res.unverified_metrics}")
    for ex in res.unverified_examples:
        print(f"  - {ex}")
    for u in res.empty_texts:
        print(f"Пустой текст: {u}")
    print(f"Вызовов LLM: {llm.calls}")
    return 0 if not res.missing else 1


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    p = argparse.ArgumentParser(prog="aidigest", description="Сбор кейсов внедрения ИИ")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="регулярный цикл")
    r.add_argument("--first-run", action="store_true", help="бюджет первого запуска (first_run_budget)")
    r.add_argument("--budget", type=float, help="лимит кредитов Tavily на запуск")
    r.add_argument("--levels", help="уровни через запятую: мир,регионы РФ,Свердловская область")
    r.add_argument("--days", type=int, help="окно свежести, дней")
    r.add_argument("--offline", action="store_true", help="только кеш, без внешних вызовов")
    r.set_defaults(func=cmd_run)

    e = sub.add_parser("enrich", help="дозаполнение архивных кейсов по сохранённым материалам")
    e.add_argument("--limit", type=_positive_int, required=True, help="максимум кейсов за запуск")
    e.add_argument("--offline", action="store_true", help="LLM только из кеша")
    e.set_defaults(func=cmd_enrich)

    v = sub.add_parser("eval", help="проверка извлечения на эталонных кейсах")
    v.add_argument("--fetch-only", action="store_true", help="только скачать тексты статей (без LLM)")
    v.add_argument("--offline", action="store_true", help="LLM только из кеша")
    v.set_defaults(func=cmd_eval)

    args = p.parse_args(argv)
    return args.func(args)
