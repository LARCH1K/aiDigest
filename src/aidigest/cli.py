"""Консольные команды: run, export (и eval — проверка на эталоне)."""
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
from aidigest.export_excel import export_xlsx
from aidigest.failure import explain, failure_reason
from aidigest.models import Level
from aidigest.registry import SourceRegistry
from aidigest.store import CaseStore
from aidigest.usage import MonthlyUsage, fetch_tavily_usage

ROOT = Path(__file__).resolve().parents[2]


def _data_dir() -> Path:
    return Path(os.environ.get("AIDIGEST_DATA_DIR") or ROOT / "data")


_CRED_KEYS = {"litellm.env": LITELLM_KEYS, "tavily.env": TAVILY_KEYS}


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


def _export(store: CaseStore, report, today: date) -> Path:
    out = _data_dir() / "out" / f"cases_{today.isoformat()}.xlsx"
    return export_xlsx(store.load().cases, report, out)


def cmd_run(args) -> int:
    """Любой неудачный запуск печатает ровно одну строку «Причина: …» (её показывает веб-интерфейс).
    Коды выхода: 0 — успех, 1 — ошибка, 2 — месячный лимит кредитов исчерпан."""
    try:
        settings = load_settings(ROOT / "config" / "settings.yaml")
        if args.days:
            settings.freshness_days = args.days
        return _run_all(args, settings)
    except MissingCreds as e:
        print(f"Причина: {e}")
        return 1
    except Exception as e:
        traceback.print_exc()
        print(f"Причина: {explain(e)}")
        return 1


def _run_all(args, settings) -> int:
    """Сбор целиком (включая сверку кредитов с Tavily)."""
    from aidigest.pipeline import Deps, run_cycle
    from aidigest.search import TavilySearch

    requested = args.budget if args.budget is not None else (
        settings.first_run_budget if args.first_run else settings.run_budget)
    today = date.today()
    usage = MonthlyUsage(_data_dir() / "credits.json", settings.monthly_limit, settings.monthly_warn_share)
    tavily = _creds("tavily.env", args.offline)
    actual = fetch_tavily_usage(tavily.get("TAVILY_TOKEN"))
    total = usage.cap(today, requested)
    if actual is not None:
        # Фактический расход по данным Tavily — главный: наш учёт мог что-то пропустить.
        print(f"Кредиты по данным Tavily: {actual.used:g} из {actual.limit:g}.")
        usage.sync(today, actual.used)
        total = min(total, actual.remaining)
    if requested > 0 and total <= 0:
        spent, limit = (actual.used, actual.limit) if actual else (usage.spent(today), settings.monthly_limit)
        print(f"Лимит Tavily исчерпан: потрачено {spent:g} из {limit:g}. Запуск отменён.")
        print("Причина: Месячный лимит кредитов Tavily исчерпан — новый сбор возможен после пополнения.")
        return 2
    if total < requested:
        print(f"Бюджет запуска урезан до остатка месячного лимита: {total:g} вместо {requested:g}.")
    budget = CreditBudget(total, settings.confirm_share)
    cache = DiskCache(_data_dir() / "cache")
    deps = Deps(
        search=TavilySearch(tavily.get("TAVILY_TOKEN"), cache, budget, offline=args.offline),
        llm=_llm(settings, cache, args.offline),
        registry=SourceRegistry.load(ROOT / "config" / "sources.yaml"),
        store=CaseStore(_data_dir() / "cases.json"),
        queries=load_queries(ROOT / "config" / "queries.yaml"),
        settings=settings, budget=budget,
    )
    try:
        report = run_cycle(deps, _parse_levels(args.levels), today)
    finally:
        usage.record(today, budget.spent)  # учитываем расход, даже если запуск упал
    rows = report.as_rows()
    rows["Кредитов Tavily за месяц"] = f"{usage.spent(today):g} из {settings.monthly_limit:g}"
    warning = usage.warning(today)
    if warning:
        print(warning)
    for k, v in rows.items():
        print(f"{k}: {v}")
    print(f"Excel: {_export(deps.store, rows, today)}")
    reason = failure_reason(report)
    if reason is not None:
        print(f"Причина: {reason}")
        return 1
    return 0


def cmd_export(args) -> int:
    print(f"Excel: {_export(CaseStore(_data_dir() / 'cases.json'), None, date.today())}")
    return 0


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

    e = sub.add_parser("export", help="Excel из базы без поиска")
    e.set_defaults(func=cmd_export)

    v = sub.add_parser("eval", help="проверка извлечения на эталонных кейсах")
    v.add_argument("--fetch-only", action="store_true", help="только скачать тексты статей (без LLM)")
    v.add_argument("--offline", action="store_true", help="LLM только из кеша")
    v.set_defaults(func=cmd_eval)

    args = p.parse_args(argv)
    return args.func(args)
