"""Запуски сбора с сайта: не больше одного одновременно, итоги и история хранятся в файлах.

<data>/web/run.lock          — идёт запуск: {"run_id", "pid", "started"}
<data>/web/runs/<id>.log     — вывод `python -m aidigest run`
<data>/web/runs/<id>.json    — итог: {"run_id", "started", "finished", "exit_code", "state"}
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

REPORT_PREFIXES = ("Кредитов", "Вызовов", "Статей", "Кандидатов", "Кейсов", "Подтверждений", "Бюджет", "Флаг:")
STATE_LABEL = {"running": "идёт", "ok": "успешно", "error": "ошибка", "limit": "месячный лимит исчерпан",
               "interrupted": "прервано"}
STALE_EMPTY_LOCK_SECONDS = 60
# Сбор длится 5–15 минут. Запуск старше этого считаем прерванным: после перезагрузки Windows
# номер процесса может достаться другой программе, и проверка «процесс жив» обманется.
MAX_RUN_AGE = timedelta(hours=3)
# Один веб-сервер, много потоков: проверка и создание блокировки не должны перемежаться.
_STATE_LOCK = threading.RLock()


class AlreadyRunning(Exception):
    pass


class MonthExhausted(Exception):
    pass


@dataclass
class RunInfo:
    run_id: str
    started: datetime
    state: str = "running"
    finished: datetime | None = None
    exit_code: int | None = None
    log_path: Path | None = None
    report: dict[str, str] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return STATE_LABEL.get(self.state, self.state)

    @property
    def minutes(self) -> int:
        end = self.finished or datetime.now()
        return max(0, int((end - self.started).total_seconds() // 60))


def parse_report(log_text: str) -> dict[str, str]:
    """Строки отчёта CLI вида «Ключ: значение» (у флагов ключ сам содержит двоеточие)."""
    out: dict[str, str] = {}
    for line in log_text.splitlines():
        line = line.strip()
        if not line.startswith(REPORT_PREFIXES) or ": " not in line:
            continue
        key, value = line.rsplit(": ", 1)
        out[key] = value
    return out


def default_pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return bool(ok) and code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class RunManager:
    def __init__(self, data_dir: Path, project_root: Path, popen=subprocess.Popen,
                 pid_alive: Callable[[int], bool] = default_pid_alive, now: Callable[[], datetime] = datetime.now):
        self.data_dir = Path(data_dir)
        self.project_root = Path(project_root)
        self.web_dir = self.data_dir / "web"
        self.runs_dir = self.web_dir / "runs"
        self.lock = self.web_dir / "run.lock"
        self._popen = popen
        self._pid_alive = pid_alive
        self._now = now

    # --- кредиты ---
    TAVILY_CACHE_SECONDS = 60

    def _tavily(self):
        """Фактический расход по данным Tavily (GET /usage, бесплатно), с кешем на минуту. None — недоступно."""
        import time
        from aidigest import usage as usage_mod
        cached = getattr(self, "_tavily_cache", None)
        if cached and time.monotonic() - cached[0] < self.TAVILY_CACHE_SECONDS:
            return cached[1]
        env = self.project_root / "tavily.env"
        token = None
        if env.exists():
            from aidigest.creds import load_env_file
            token = load_env_file(env).get("TAVILY_TOKEN")
        result = usage_mod.fetch_tavily_usage(token, timeout=5)
        self._tavily_cache = (time.monotonic(), result)
        return result

    def _local(self):
        from aidigest.config import load_settings
        from aidigest.usage import MonthlyUsage
        path = self.project_root / "config" / "settings.yaml"
        settings = load_settings(path) if path.exists() else None
        limit = settings.monthly_limit if settings else 1000
        return MonthlyUsage(self.data_dir / "credits.json", limit), limit, (settings.run_budget if settings else 30)

    def credits(self) -> dict:
        """Расход кредитов для страницы: по данным Tavily, а если он недоступен — по нашему учёту."""
        actual = self._tavily()
        if actual is not None:
            return {"spent": actual.used, "limit": actual.limit, "source": "tavily"}
        usage, limit, _ = self._local()
        return {"spent": usage.spent(self._now().date()), "limit": limit, "source": "local"}

    def month_spent(self) -> float:
        return self.credits()["spent"]

    def month_limit(self) -> float:
        return self.credits()["limit"]

    def run_budget(self) -> float:
        return self._local()[2]

    def month_remaining(self) -> float:
        c = self.credits()
        return max(0.0, c["limit"] - c["spent"])

    # --- состояние ---
    def _result_path(self, run_id: str) -> Path:
        return self.runs_dir / f"{run_id}.json"

    def _log_path(self, run_id: str) -> Path:
        return self.runs_dir / f"{run_id}.log"

    def _write_result(self, run_id: str, started: datetime, state: str, exit_code: int | None) -> None:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self._result_path(run_id).write_text(json.dumps({
            "run_id": run_id, "started": started.isoformat(), "finished": self._now().isoformat(),
            "exit_code": exit_code, "state": state}, ensure_ascii=False), encoding="utf-8")

    def current(self) -> RunInfo | None:
        """Идущий запуск или None. Заодно снимает блокировку закончившихся и прерванных запусков."""
        with _STATE_LOCK:
            return self._current()

    def _current(self) -> RunInfo | None:
        try:
            raw = self.lock.read_text(encoding="utf-8")
            mtime = self.lock.stat().st_mtime
        except FileNotFoundError:
            return None
        try:
            data = json.loads(raw or "{}")
            run_id, pid = data["run_id"], int(data["pid"])
            started = datetime.fromisoformat(data["started"])
        except (ValueError, KeyError, TypeError):
            # блокировку только что создали и ещё не дописали (или файл испорчен); старую — убираем
            if self._now().timestamp() - mtime > STALE_EMPTY_LOCK_SECONDS:
                self.lock.unlink(missing_ok=True)
                return None
            return RunInfo(run_id="", started=self._now())
        if self._result_path(run_id).exists():
            self.lock.unlink(missing_ok=True)
            return None
        pid_file = self.runs_dir / f"{run_id}.pid"
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())  # настоящий номер обёртки, если уже записан
        except (OSError, ValueError):
            pass
        if self._now() - started > MAX_RUN_AGE or not self._pid_alive(pid):
            self._write_result(run_id, started, "interrupted", None)
            self.lock.unlink(missing_ok=True)
            return None
        return RunInfo(run_id=run_id, started=started, log_path=self._log_path(run_id))

    def start(self) -> RunInfo:
        with _STATE_LOCK:
            return self._start()

    def _start(self) -> RunInfo:
        if self.month_remaining() <= 0:
            raise MonthExhausted()
        if self._current() is not None:
            raise AlreadyRunning()
        self.web_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise AlreadyRunning() from None
        started = self._now().replace(microsecond=0)
        run_id = started.strftime("%Y%m%d-%H%M%S")
        try:
            kw = dict(cwd=str(self.project_root), env={**os.environ, "AIDIGEST_DATA_DIR": str(self.data_dir)},
                      stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if sys.platform == "win32":
                # без окна консоли и отдельно от сервера: Ctrl+C в окне сервера не оборвёт сбор
                kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            else:
                kw["start_new_session"] = True
            proc = self._popen([sys.executable, "-m", "aidigest_web.runner", run_id], **kw)
            os.write(fd, json.dumps({"run_id": run_id, "pid": proc.pid, "started": started.isoformat()}).encode())
        except Exception:
            os.close(fd)
            self.lock.unlink(missing_ok=True)
            raise
        os.close(fd)
        return RunInfo(run_id=run_id, started=started, log_path=self._log_path(run_id))

    def history(self, limit: int = 10) -> list[RunInfo]:
        if not self.runs_dir.exists():
            return []
        out = []
        for p in sorted(self.runs_dir.glob("*.json"), reverse=True)[:limit]:
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                run_id, started = d["run_id"], datetime.fromisoformat(d["started"])
                finished = datetime.fromisoformat(d["finished"]) if d.get("finished") else None
            except (OSError, ValueError, KeyError, TypeError):
                continue  # испорченная запись истории — пропускаем
            log = self._log_path(run_id)
            text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
            out.append(RunInfo(run_id=run_id, started=started, finished=finished,
                               exit_code=d.get("exit_code"), state=d.get("state", "error"),
                               log_path=log, report=parse_report(text)))
        return out

    def tail(self, run: RunInfo, lines: int = 30) -> list[str]:
        if not run.log_path or not run.log_path.exists():
            return []
        text = run.log_path.read_text(encoding="utf-8", errors="replace")
        return text.splitlines()[-lines:]

    def log_text(self, run_id: str) -> str | None:
        if not re.fullmatch(r"\d{8}-\d{6}", run_id, re.ASCII):
            return None
        p = self._log_path(run_id)
        return p.read_text(encoding="utf-8", errors="replace") if p.exists() else None
