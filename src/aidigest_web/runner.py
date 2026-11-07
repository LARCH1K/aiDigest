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


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    run_id = argv[0]
    data_dir = Path(os.environ.get("AIDIGEST_DATA_DIR") or PROJECT_ROOT / "data")
    runs = data_dir / "web" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    started = datetime.now().replace(microsecond=0)
    env = {**os.environ, "AIDIGEST_DATA_DIR": str(data_dir), "PYTHONIOENCODING": "utf-8"}
    # Настоящий номер процесса обёртки: в Windows python.exe из venv — запускалка, и Popen видит её номер.
    (runs / f"{run_id}.pid").write_text(str(os.getpid()), encoding="utf-8")
    _kill_children_with_runner()
    kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    with open(runs / f"{run_id}.log", "wb") as log:
        try:
            proc = subprocess.Popen([sys.executable, "-m", "aidigest", "run"], cwd=str(PROJECT_ROOT), env=env,
                                    stdout=log, stderr=subprocess.STDOUT, **kw)
            code = proc.wait()
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
