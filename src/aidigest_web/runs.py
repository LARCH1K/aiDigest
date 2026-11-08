"""Запуски сбора с сайта: не больше одного одновременно, итоги и история хранятся в файлах.

<data>/web/run.lock              — идёт запуск: {"run_id", "pid", "started"} (pid — справочно, не проверяется)
<data>/web/runs/<id>.heartbeat   — сборщик жив: обёртка обновляет время изменения файла каждые HEARTBEAT_SECONDS
<data>/web/runs/<id>.log         — вывод `python -m aidigest run`
<data>/web/runs/<id>.json        — итог: {"run_id", "started", "finished", "exit_code", "state", "reason"}
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

REPORT_PREFIXES = ("Кредитов", "Вызовов", "Статей", "Кандидатов", "Кейсов", "Подтверждений", "Бюджет", "Флаг:")
STATE_LABEL = {"running": "идёт", "ok": "успешно", "error": "ошибка", "limit": "месячный лимит исчерпан",
               "interrupted": "прервано", "busy": "уже шёл другой сбор"}
# Код выхода `aidigest run` → итог; остальные коды — "error".
STATE_BY_CODE = {0: "ok", 2: "limit", 3: "busy"}
STALE_EMPTY_LOCK_SECONDS = 60
# Жив ли сбор, видно по heartbeat-файлу, а не по номеру процесса: сборщик может работать
# в другом контейнере, где номера процессов не видны.
HEARTBEAT_SECONDS = 15
HEARTBEAT_STALE_SECONDS = 90
# Сбор длится 5–15 минут. Запуск старше этого считаем прерванным, даже если heartbeat свежий (сбор завис).
MAX_RUN_AGE = timedelta(hours=3)
REASON_WORKER_MISSING = "Сборщик не взял заявку — сообщите команде разработки."
REASON_HEARTBEAT_STALE = "Сбор оборвался (перезапуск или сбой сервера). Кейсы, которые он успел сохранить, уже в базе."
REASON_TOO_LONG = "Сбор шёл дольше 3 часов и остановлен как зависший. Кейсы, которые он успел сохранить, уже в базе."
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
    reason: str | None = None

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


def heartbeat_path(runs_dir: Path, run_id: str) -> Path:
    return Path(runs_dir) / f"{run_id}.heartbeat"


class RunManager:
    def __init__(self, data_dir: Path, project_root: Path, popen=subprocess.Popen,
                 now: Callable[[], datetime] = datetime.now, clock: Callable[[], float] = time.time):
        self.data_dir = Path(data_dir)
        self.project_root = Path(project_root)
        self.web_dir = self.data_dir / "web"
        self.runs_dir = self.web_dir / "runs"
        self.lock = self.web_dir / "run.lock"
        self._popen = popen
        self._now = now
        self._clock = clock  # секунды, сравниваются с mtime файлов

    # --- кредиты ---
    TAVILY_CACHE_SECONDS = 60

    def _tavily(self):
        """Фактический расход по данным Tavily (GET /usage, бесплатно), с кешем на минуту. None — недоступно."""
        from aidigest import usage as usage_mod
        cached = getattr(self, "_tavily_cache", None)
        if cached and time.monotonic() - cached[0] < self.TAVILY_CACHE_SECONDS:
            return cached[1]
        from aidigest.creds import TAVILY_KEYS, load_creds
        token = load_creds(self.project_root / "tavily.env", TAVILY_KEYS).get("TAVILY_TOKEN")
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

    def _write_result(self, run_id: str, started: datetime, state: str, exit_code: int | None,
                      reason: str | None = None) -> None:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self._result_path(run_id).write_text(json.dumps({
            "run_id": run_id, "started": started.isoformat(), "finished": self._now().isoformat(),
            "exit_code": exit_code, "state": state, "reason": reason}, ensure_ascii=False), encoding="utf-8")

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
            run_id = data["run_id"]
            started = datetime.fromisoformat(data["started"])
        except (ValueError, KeyError, TypeError):
            # блокировку только что создали и ещё не дописали (или файл испорчен); старую — убираем
            if self._clock() - mtime > STALE_EMPTY_LOCK_SECONDS:
                self.lock.unlink(missing_ok=True)
                return None
            return RunInfo(run_id="", started=self._now())
        if self._result_path(run_id).exists():
            self.lock.unlink(missing_ok=True)
            return None
        reason = self._dead_reason(run_id, started, mtime)
        if reason:
            self._write_result(run_id, started, "interrupted", None, reason)
            self.lock.unlink(missing_ok=True)
            return None
        return RunInfo(run_id=run_id, started=started, log_path=self._log_path(run_id))

    def _dead_reason(self, run_id: str, started: datetime, lock_mtime: float) -> str | None:
        """Почему запуск считается прерванным; None — ещё жив."""
        if self._now() - started > MAX_RUN_AGE:
            return REASON_TOO_LONG
        try:
            beat = heartbeat_path(self.runs_dir, run_id).stat().st_mtime
        except FileNotFoundError:
            # сборщик ещё не отозвался: даём ему время, пока свежа сама заявка
            return None if self._clock() - lock_mtime < HEARTBEAT_STALE_SECONDS else REASON_WORKER_MISSING
        return None if self._clock() - beat < HEARTBEAT_STALE_SECONDS else REASON_HEARTBEAT_STALE

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
                               log_path=log, report=parse_report(text), reason=d.get("reason")))
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
