"""Сводка для сравнения контрольного JSON и кейсов в PostgreSQL."""

import argparse
import json
from pathlib import Path

from aidigest.db.engine import make_engine
from aidigest.models import Case, ConfirmationStatus, Flag, Level
from aidigest.store import PgCaseStore


def percentage(count: int, total: int) -> str:
    return f"{100 * count / total:.1f}%" if total else "нет данных"


def show(label: str, cases: list[Case]) -> None:
    total = len(cases)
    metrics = [metric for case in cases for metric in case.metrics]
    print(f"{label}: {total} кейсов")
    print("  С показателями:", percentage(sum(bool(case.metrics) for case in cases), total))
    for status in (ConfirmationStatus.CONFIRMED, ConfirmationStatus.CONFLICT):
        count = sum(case.confirmation_status == status for case in cases)
        print(f"  Статус «{status}»:", percentage(count, total))
    print("  Проверенные цитаты:", percentage(sum(metric.quote_verified for metric in metrics), len(metrics)))
    for level in Level:
        print(f"  {level}: {sum(case.level == level for case in cases)}")
    print(f"  Флаг «{Flag.QUOTE_NOT_FOUND}»: {sum(Flag.QUOTE_NOT_FOUND in case.flags for case in cases)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path, help="путь к контрольному JSON с кейсами")
    baseline = json.loads(parser.parse_args().baseline.read_text(encoding="utf-8"))
    old = [Case.model_validate(case) for case in baseline["cases"]]

    engine = make_engine()
    try:
        new = PgCaseStore(engine).load().cases
    finally:
        engine.dispose()
    show("Контрольный набор", old)
    show("PostgreSQL", new)


if __name__ == "__main__":
    main()
