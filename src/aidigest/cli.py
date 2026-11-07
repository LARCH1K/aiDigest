"""Консольные команды: run, export (и eval — проверка на эталоне)."""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from aidigest.budget import CreditBudget
from aidigest.cache import DiskCache
from aidigest.config import load_queries, load_settings
from aidigest.creds import load_env_file
from aidigest.export_excel import export_xlsx
from aidigest.models import Level
from aidigest.registry import SourceRegistry
from aidigest.store import CaseStore

ROOT = Path(__file__).resolve().parents[2]


def _data_dir() -> Path:
    return Path(os.environ.get("AIDIGEST_DATA_DIR") or ROOT / "data")


def _creds(name: str, offline: bool) -> dict[str, str]:
    path = ROOT / name
    if not path.exists():
        if offline:
            return {}
        raise SystemExit(f"Не найден файл {name} в корне проекта.")
    return load_env_file(path)


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
    export_xlsx(store.load().cases, report, out)
    return out


def cmd_run(args) -> int:
    from aidigest.pipeline import Deps, run_cycle
    from aidigest.search import TavilySearch

    settings = load_settings(ROOT / "config" / "settings.yaml")
    if args.days:
        settings.freshness_days = args.days
    total = args.budget if args.budget is not None else (
        settings.first_run_budget if args.first_run else settings.run_budget)
    budget = CreditBudget(total, settings.confirm_share)
    cache = DiskCache(_data_dir() / "cache")
    tavily = _creds("tavily.env", args.offline)
    deps = Deps(
        search=TavilySearch(tavily.get("TAVILY_TOKEN"), cache, budget, offline=args.offline),
        llm=_llm(settings, cache, args.offline),
        registry=SourceRegistry.load(ROOT / "config" / "sources.yaml"),
        store=CaseStore(_data_dir() / "cases.json"),
        queries=load_queries(ROOT / "config" / "queries.yaml"),
        settings=settings, budget=budget,
    )
    today = date.today()
    report = run_cycle(deps, _parse_levels(args.levels), today)
    rows = report.as_rows()
    for k, v in rows.items():
        print(f"{k}: {v}")
    print(f"Excel: {_export(deps.store, rows, today)}")
    return 0


def cmd_export(args) -> int:
    print(f"Excel: {_export(CaseStore(_data_dir() / 'cases.json'), None, date.today())}")
    return 0


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

    args = p.parse_args(argv)
    return args.func(args)
