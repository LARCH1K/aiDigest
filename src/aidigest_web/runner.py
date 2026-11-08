"""Обёртка запуска с сайта: выполняет `python -m aidigest run` и записывает итог в файл.

Запускается отдельным процессом (python -m aidigest_web.runner <run_id>), поэтому итог не теряется,
даже если веб-сервер перезапустят во время сбора.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

from aidigest_web import PROJECT_ROOT
from aidigest_web.runs import HEARTBEAT_SECONDS, STATE_BY_CODE, heartbeat_path

REASON_PREFIX = "Причина: "


_JOBS: list = []  # держим дескрипторы Job Object открытыми, пока жива обёртка


def _kill_children_with_runner() -> None:
    """Windows: обёртка помещает саму себя в Job Object с KILL_ON_JOB_CLOSE ещё до запуска сбора.
    Все её потомки попадают туда автоматически и умирают вместе с ней.

    Иначе после «Снять задачу» с обёртки сбор продолжил бы работать, сайт счёл бы запуск
    прерванным и разрешил второй — два сбора тратили бы кредиты одновременно.
    В Linux сбор живёт в сессии обёртки; ошибки здесь не мешают самому сбору."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        class IoCounters(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]

        class BasicLimit(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class ExtendedLimit(ctypes.Structure):
            _fields_ = [("Basic", BasicLimit), ("Io", IoCounters), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        job = k32.CreateJobObjectW(None, None)
        info = ExtendedLimit()
        info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))  # ExtendedLimitInformation
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.AssignProcessToJobObject(job, k32.GetCurrentProcess())
        _JOBS.append(job)
    except Exception:
        pass


def _touch(path: Path) -> None:
    path.touch()


def _heartbeat(path: Path, stop: threading.Event) -> None:
    """Обновляет heartbeat, пока не попросят остановиться: по нему сайт видит, что сбор жив."""
    while not stop.wait(HEARTBEAT_SECONDS):
        try:
            _touch(path)
        except OSError:
            pass  # временная ошибка диска не должна ронять сбор


def _reason(log_path: Path) -> str | None:
    """Последняя строка «Причина: …» из лога, без префикса."""
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        if line.startswith(REASON_PREFIX):
            return line[len(REASON_PREFIX):].strip() or None
    return None


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    run_id = argv[0]
    data_dir = Path(os.environ.get("AIDIGEST_DATA_DIR") or PROJECT_ROOT / "data")
    runs = data_dir / "web" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    started = datetime.now().replace(microsecond=0)
    # PYTHONUNBUFFERED: вывод попадает в лог сразу, иначе страница минутами не видит ход сбора.
    env = {**os.environ, "AIDIGEST_DATA_DIR": str(data_dir), "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    beat = heartbeat_path(runs, run_id)
    _touch(beat)  # первое обновление — до запуска сбора
    stop = threading.Event()
    beater = threading.Thread(target=_heartbeat, args=(beat, stop), name="heartbeat", daemon=True)
    beater.start()
    _kill_children_with_runner()
    kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    log_path = runs / f"{run_id}.log"
    try:
        with open(log_path, "wb") as log:
            try:
                proc = subprocess.Popen([sys.executable, "-m", "aidigest", "run"], cwd=str(PROJECT_ROOT), env=env,
                                        stdout=log, stderr=subprocess.STDOUT, **kw)
                code = proc.wait()
            except Exception as e:  # не удалось даже запустить процесс
                log.write(f"Не удалось запустить сбор: {e}\n{REASON_PREFIX}не удалось запустить сбор.\n"
                          .encode("utf-8"))
                code = 1
    finally:
        stop.set()
        beater.join()
    result = {"run_id": run_id, "started": started.isoformat(), "finished": datetime.now().isoformat(),
              "exit_code": code, "state": STATE_BY_CODE.get(code, "error"), "reason": _reason(log_path)}
    tmp = runs / f"{run_id}.json.tmp"
    tmp.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, runs / f"{run_id}.json")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
