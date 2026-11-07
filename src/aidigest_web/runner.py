"""Обёртка запуска с сайта: выполняет `python -m aidigest run` и записывает итог в файл.

Запускается отдельным процессом (python -m aidigest_web.runner <run_id>), поэтому итог не теряется,
даже если веб-сервер перезапустят во время сбора.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from aidigest_web import PROJECT_ROOT

STATE_BY_CODE = {0: "ok", 2: "limit"}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    run_id = argv[0]
    data_dir = Path(os.environ.get("AIDIGEST_DATA_DIR") or PROJECT_ROOT / "data")
    runs = data_dir / "web" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    started = datetime.now().replace(microsecond=0)
    env = {**os.environ, "AIDIGEST_DATA_DIR": str(data_dir), "PYTHONIOENCODING": "utf-8"}
    with open(runs / f"{run_id}.log", "wb") as log:
        try:
            code = subprocess.run([sys.executable, "-m", "aidigest", "run"], cwd=str(PROJECT_ROOT), env=env,
                                  stdout=log, stderr=subprocess.STDOUT).returncode
        except Exception as e:  # не удалось даже запустить процесс
            log.write(f"Не удалось запустить сбор: {e}\n".encode("utf-8"))
            code = 1
    result = {"run_id": run_id, "started": started.isoformat(), "finished": datetime.now().isoformat(),
              "exit_code": code, "state": STATE_BY_CODE.get(code, "error")}
    tmp = runs / f"{run_id}.json.tmp"
    tmp.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, runs / f"{run_id}.json")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
