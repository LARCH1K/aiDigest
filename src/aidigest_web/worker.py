"""Сборщик для сервера: берёт заявки на сбор из папки данных и выполняет их по одной.

Сайт в режиме очереди (AIDIGEST_RUN_MODE=queue) не запускает сбор сам, а пишет заявку
<data>/web/requests/<run_id>.json. Worker живёт в отдельном контейнере с той же папкой данных:
  python -m aidigest_web.worker           — бесконечный цикл обработки заявок;
  python -m aidigest_web.worker --status  — «busy» (код 1), если идёт сбор, иначе «idle» (код 0);
                                            только читает состояние, блокировку не трогает.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable

from aidigest.housekeeping import backup_cases, keep_newest, prune_cache
from aidigest_web import PROJECT_ROOT, runner
from aidigest_web.runs import RunManager, heartbeat_path, requests_dir

POLL_SECONDS = 3
RUNS_KEEP = 100
EXPORTS_KEEP = 30


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


def prune_runs(data_dir: Path, keep: int = RUNS_KEEP) -> int:
    """Удаляет все файлы запусков (.json, .log, .heartbeat, старые .pid), кроме keep последних по run_id.
    Возвращает число удалённых файлов."""
    runs = Path(data_dir) / "web" / "runs"
    if not runs.is_dir():
        return 0
    files = [p for p in runs.iterdir() if p.is_file()]
    # run_id — время запуска (ГГГГММДД-ЧЧММСС), поэтому порядок имён — порядок запусков
    run_ids = sorted({p.name.split(".", 1)[0] for p in files})
    old = set(run_ids[:-keep] if keep > 0 else run_ids)
    removed = 0
    for path in files:
        if path.name.split(".", 1)[0] in old:
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def housekeep(data_dir: Path) -> None:
    """Очистка перед сбором: старый кеш, история запусков, старые выгрузки Excel."""
    data_dir = Path(data_dir)
    prune_cache(data_dir, time.time())
    prune_runs(data_dir)
    keep_newest(data_dir / "out", "*.xlsx", EXPORTS_KEEP)


def process_once(data_dir: Path, run: Callable[[list[str]], int] = runner.main,
                 before: Callable[[], None] = lambda: None,
                 after: Callable[[int], None] = lambda code: None) -> str | None:
    """Выполняет самую старую действующую заявку и возвращает её run_id; None — действующих заявок нет.
    Отменённые заявки пропускаются сразу, без ожидания следующего опроса."""
    data_dir = Path(data_dir)
    runs = data_dir / "web" / "runs"
    while (run_id := _claim(data_dir)) is not None:
        # heartbeat — до проверки блокировки: иначе на границе ожидания сайт может решить,
        # что сборщик не взял заявку, хотя он её уже взял
        beat = heartbeat_path(runs, run_id)
        runs.mkdir(parents=True, exist_ok=True)
        beat.touch()
        if _lock_run_id(data_dir) != run_id:
            # сайт уже счёл запуск прерванным и снял блокировку — запускать поздно
            beat.unlink(missing_ok=True)
            print(f"Заявка {run_id} пропущена: запуск уже снят сайтом", file=sys.stderr)
            continue
        before()
        code = run([run_id])
        after(code)
        return run_id
    return None


def loop(data_dir: Path, iterations: int | None = None, sleep: Callable[[float], None] = time.sleep,
         before: Callable[[], None] = lambda: None, after: Callable[[int], None] = lambda code: None) -> int:
    """Цикл обработки заявок; iterations — для тестов (None — бесконечно).
    Ошибка одной заявки не роняет worker: иначе контейнер ушёл бы в цикл перезапусков."""
    done = 0
    while iterations is None or done < iterations:
        done += 1
        try:
            if process_once(data_dir, before=before, after=after) is not None:
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
        busy = RunManager(data_dir, PROJECT_ROOT).is_running()
        print("busy" if busy else "idle")
        return 1 if busy else 0

    def before() -> None:
        # сбой очистки не должен мешать сбору
        try:
            housekeep(data_dir)
        except Exception:
            print("Очистка перед сбором не удалась:", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)

    def after(code: int) -> None:
        if code == 0:
            backup_cases(data_dir, datetime.now())

    print(f"aiDigest worker: жду заявки в {requests_dir(data_dir)}", flush=True)
    return loop(data_dir, before=before, after=after)


if __name__ == "__main__":
    raise SystemExit(main())
