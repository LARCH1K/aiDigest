"""Сборщик для сервера: берёт заявки на сбор из папки данных и выполняет их по одной.

Сайт в режиме очереди (AIDIGEST_RUN_MODE=queue) не запускает сбор сам, а пишет заявку
<data>/web/requests/<run_id>.json. Worker живёт в отдельном контейнере с той же папкой данных:
  python -m aidigest_web.worker           — бесконечный цикл обработки заявок;
  python -m aidigest_web.worker --status  — «busy» (код 1), если идёт сбор, иначе «idle» (код 0).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Callable

from aidigest_web import PROJECT_ROOT, runner
from aidigest_web.runs import RunManager, requests_dir

POLL_SECONDS = 3


def _data_dir() -> Path:
    return Path(os.environ.get("AIDIGEST_DATA_DIR") or PROJECT_ROOT / "data")


def _claim(data_dir: Path) -> str | None:
    """run_id самой старой заявки; файл заявки удаляется. None — заявок нет."""
    folder = requests_dir(data_dir)
    if not folder.exists():
        return None
    # run_id — время запуска (ГГГГММДД-ЧЧММСС), поэтому порядок имён — порядок заявок
    for path in sorted(folder.glob("*.json")):
        try:
            raw = path.read_text(encoding="utf-8")
            path.unlink()
        except FileNotFoundError:
            continue  # заявку только что убрали — берём следующую
        try:
            return json.loads(raw)["run_id"]
        except (ValueError, KeyError, TypeError):
            print(f"Испорченная заявка {path.name} удалена", file=sys.stderr)
    return None


def _lock_run_id(data_dir: Path) -> str | None:
    try:
        return json.loads((data_dir / "web" / "run.lock").read_text(encoding="utf-8")).get("run_id")
    except (OSError, ValueError, AttributeError):
        return None


def process_once(data_dir: Path, run: Callable[[list[str]], int] = runner.main,
                 before: Callable[[], None] = lambda: None,
                 after: Callable[[int], None] = lambda code: None) -> str | None:
    """Выполняет самую старую заявку и возвращает её run_id; None — заявок нет или заявка отменена."""
    data_dir = Path(data_dir)
    run_id = _claim(data_dir)
    if run_id is None:
        return None
    if _lock_run_id(data_dir) != run_id:
        # сайт уже счёл запуск прерванным и снял блокировку — запускать поздно
        print(f"Заявка {run_id} пропущена: запуск уже снят сайтом", file=sys.stderr)
        return None
    before()
    code = run([run_id])
    after(code)
    return run_id


def loop(data_dir: Path, iterations: int | None = None, sleep: Callable[[float], None] = time.sleep) -> int:
    """Цикл обработки заявок; iterations — для тестов (None — бесконечно).
    Ошибка одной заявки не роняет worker: иначе контейнер ушёл бы в цикл перезапусков."""
    done = 0
    while iterations is None or done < iterations:
        done += 1
        try:
            if process_once(data_dir) is not None:
                continue  # сразу проверяем, нет ли следующей заявки
        except Exception:
            traceback.print_exc(file=sys.stderr)
        sleep(POLL_SECONDS)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="aidigest_web.worker", description="Сборщик aiDigest: выполняет заявки сайта")
    p.add_argument("--status", action="store_true", help="напечатать busy/idle (код 1/0) и выйти")
    args = p.parse_args(sys.argv[1:] if argv is None else argv)
    data_dir = _data_dir()
    if args.status:
        busy = RunManager(data_dir, PROJECT_ROOT).current() is not None
        print("busy" if busy else "idle")
        return 1 if busy else 0
    print(f"aiDigest worker: жду заявки в {requests_dir(data_dir)}", flush=True)
    return loop(data_dir)


if __name__ == "__main__":
    raise SystemExit(main())
