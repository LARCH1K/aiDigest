"""Разбор вывода `aidigest run` и запуск сбора: строки отчёта, причина неудачи, таблица runs, подпроцесс."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import Engine, delete, select, update
from sqlalchemy.exc import IntegrityError

from aidigest.config import Settings
from aidigest.db.schema import runs
from aidigest.models import Level
from aidigest.usage import fetch_tavily_usage

REPORT_PREFIXES = ("Новых поисковых запросов", "Кредитов", "Вызовов", "Статей",
                   "Кандидатов", "Кейсов", "Подтверждений", "Бюджет", "Флаг:")
STATE_LABEL = {"running": "идёт", "ok": "успешно", "error": "ошибка", "limit": "месячный лимит исчерпан",
               "interrupted": "прервано"}
REASON_PREFIX = "Причина: "

STATE_BY_CODE = {0: "ok", 2: "limit"}  # прочие коды — "error"
REASON_INTERRUPTED = "Сбор прерван перезапуском сервера. Кейсы, которые он успел сохранить, уже в базе."
REASON_CRASHED = "Сборщик завершился аварийно — сообщите команде разработки."
REASON_SPAWN_FAILED = "Не удалось запустить сбор — сообщите команде разработки."
RUNS_KEEP = 100
LOG_TAIL_LINES = 30
USAGE_TTL = 60.0  # секунд кеша ответа Tavily
FINISH_RETRIES = 3  # попыток закрыть запись при сбое БД
FINISH_PAUSE = 0.5  # секунд между попытками
STOP_TIMEOUT = 3  # секунд ожидания после каждого сигнала завершения

log = logging.getLogger(__name__)


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


def last_reason(log_text: str) -> str | None:
    """Последняя строка «Причина: …» из лога, без префикса."""
    for line in reversed(log_text.splitlines()):
        if line.startswith(REASON_PREFIX):
            return line[len(REASON_PREFIX):].strip() or None
    return None


class AlreadyRunning(Exception):
    """Сбор уже идёт."""


class MonthExhausted(Exception):
    """Месячный лимит кредитов Tavily исчерпан."""


class RunServiceStopping(Exception):
    """Сервис завершает работу."""


def _to_local(dt: datetime | None) -> datetime | None:
    """Время в записях — наивное локальное (как datetime.now()); в базе — timestamptz."""
    return dt.astimezone().replace(tzinfo=None) if dt is not None else None


def _to_db(dt: datetime | None) -> datetime | None:
    """Наивное время считаем локальным и делаем осведомлённым для timestamptz."""
    return dt.astimezone() if dt is not None else None


@dataclass
class RunRecord:
    run_id: str
    state: str
    started: datetime
    finished: datetime | None
    exit_code: int | None
    reason: str | None
    report: dict[str, str] = field(default_factory=dict)
    params: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return STATE_LABEL.get(self.state, self.state)

    @property
    def minutes(self) -> int:
        end = self.finished or datetime.now()
        return max(0, int((end - self.started).total_seconds() // 60))


def _record(row) -> RunRecord:
    return RunRecord(run_id=row.id, state=row.state, started=_to_local(row.started),
                     finished=_to_local(row.finished), exit_code=row.exit_code, reason=row.reason,
                     report=dict(row.report or {}), params=dict(row.params or {}))


class RunStore:
    """Таблица runs."""

    def __init__(self, engine: Engine):
        self.engine = engine

    def create(self, run_id: str, started: datetime, params: dict) -> None:
        try:
            with self.engine.begin() as c:
                c.execute(runs.insert().values(id=run_id, state="running", started=_to_db(started),
                                               params=params))
        except IntegrityError as e:
            if "runs_one_running" in str(e.orig):
                raise AlreadyRunning from e
            raise

    def finish(self, run_id: str, state: str, exit_code: int | None, reason: str | None,
               report: dict, finished: datetime) -> bool:
        """Закрывает запись, только если она ещё running (повторно не перезаписывает)."""
        with self.engine.begin() as c:
            res = c.execute(update(runs).where(runs.c.id == run_id, runs.c.state == "running").values(
                state=state, exit_code=exit_code, reason=reason, report=report, finished=_to_db(finished)))
        return res.rowcount > 0

    def interrupt_running(self, now: datetime) -> int:
        with self.engine.begin() as c:
            res = c.execute(update(runs).where(runs.c.state == "running").values(
                state="interrupted", reason=REASON_INTERRUPTED, finished=_to_db(now)))
        return res.rowcount

    def current(self) -> RunRecord | None:
        with self.engine.connect() as c:
            row = c.execute(select(runs).where(runs.c.state == "running")).first()
        return _record(row) if row else None

    def get(self, run_id: str) -> RunRecord | None:
        with self.engine.connect() as c:
            row = c.execute(select(runs).where(runs.c.id == run_id)).first()
        return _record(row) if row else None

    def history(self, limit: int = 10) -> list[RunRecord]:
        with self.engine.connect() as c:
            rows = c.execute(select(runs).order_by(runs.c.started.desc()).limit(limit)).all()
        return [_record(r) for r in rows]

    def prune(self, keep: int = RUNS_KEEP) -> list[str]:
        """Оставляет `keep` последних запусков (running не трогает); возвращает id удалённых."""
        with self.engine.begin() as c:
            old = [r.id for r in c.execute(
                select(runs.c.id).where(runs.c.state != "running")
                .order_by(runs.c.started.desc()).offset(keep)).all()]
            if old:
                c.execute(delete(runs).where(runs.c.id.in_(old)))
        return old


@dataclass
class RunParams:
    budget: float | None = None
    levels: list[Level] | None = None
    days: int | None = None
    offline: bool = False

    def to_argv(self) -> list[str]:
        argv: list[str] = []
        if self.budget is not None:
            argv += ["--budget", f"{self.budget:g}"]
        if self.levels:
            argv += ["--levels", ",".join(str(x) for x in self.levels)]
        if self.days is not None:
            argv += ["--days", str(self.days)]
        if self.offline:
            argv.append("--offline")
        return argv

    def as_dict(self) -> dict:
        out: dict = {}
        if self.budget is not None:
            out["budget"] = int(self.budget) if float(self.budget).is_integer() else self.budget
        if self.levels:
            out["levels"] = [str(x) for x in self.levels]
        if self.days is not None:
            out["days"] = self.days
        if self.offline:
            out["offline"] = True
        return out


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return None


@dataclass(frozen=True)
class _RunOutcome:
    run_id: str
    state: str
    code: int | None
    reason: str | None
    report: dict[str, str]
    finished: datetime


class RunService:
    """Запуск сбора подпроцессом `python -m aidigest run`; учёт в таблице runs, вывод — в файл лога."""

    def __init__(self, store: RunStore, data_dir: Path, project_root: Path, settings: Settings,
                 tavily_token: str | None, popen=subprocess.Popen, now=datetime.now,
                 fetch_usage=fetch_tavily_usage):
        self.store = store
        self.data_dir = Path(data_dir)
        self.project_root = Path(project_root)
        self.settings = settings
        self.tavily_token = tavily_token
        self._popen = popen
        self._now = now
        self._fetch_usage = fetch_usage
        self._usage_cache: tuple[float, object] | None = None
        self._watchers: list[threading.Thread] = []
        self._run_lock = threading.Lock()
        self._stopping = False
        self._child: tuple[str, subprocess.Popen, threading.Thread] | None = None
        self._pending_finish: _RunOutcome | None = None

    @property
    def _logs_dir(self) -> Path:
        return self.data_dir / "runs"

    def _usage(self):
        if not self.tavily_token:
            return None
        if self._usage_cache and time.monotonic() - self._usage_cache[0] < USAGE_TTL:
            return self._usage_cache[1]
        usage = self._fetch_usage(self.tavily_token)
        self._usage_cache = (time.monotonic(), usage)  # None тоже кешируем
        return usage

    def credits(self) -> dict:
        usage = self._usage()
        return {"known": usage is not None,
                "used": usage.used if usage else None,
                "limit": usage.limit if usage else None,
                "remaining": usage.remaining if usage else None,
                "plan": usage.plan if usage else "",
                "run_budget": self.settings.run_budget}

    def start(self, params: RunParams | None = None) -> str:
        params = params or RunParams()
        cr = None if params.offline else self.credits()
        with self._run_lock:
            if self._stopping:
                raise RunServiceStopping
            self._flush_finish()
            if cr and cr["known"] and cr["remaining"] <= 0:
                raise MonthExhausted
            return self._start_child(params)

    def _start_child(self, params: RunParams) -> str:
        started = self._now()
        run_id = f"{started:%Y%m%d-%H%M%S}-{uuid4().hex}"
        self.store.create(run_id, started, params.as_dict())
        log_path = self._logs_dir / f"{run_id}.log"
        try:
            self._logs_dir.mkdir(parents=True, exist_ok=True)
            env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8",
                   "AIDIGEST_DATA_DIR": str(self.data_dir)}
            kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
            with open(log_path, "wb") as logf:  # дескриптор родителя закрывается сразу после popen
                proc = self._popen([sys.executable, "-m", "aidigest", "run", *params.to_argv()],
                                   cwd=self.project_root, stdout=logf, stderr=subprocess.STDOUT,
                                   env=env, **kwargs)
        except Exception:
            self._finish(run_id, "error", None, REASON_SPAWN_FAILED, {})
            raise
        self._watchers = [w for w in self._watchers if w.is_alive()]
        t = threading.Thread(target=self._watch, args=(run_id, proc, log_path), daemon=True,
                             name=f"run-{run_id}")
        self._child = (run_id, proc, t)
        self._watchers.append(t)
        t.start()
        return run_id

    def _watch(self, run_id: str, proc, log_path: Path) -> None:
        try:
            code = proc.wait()
            text = _read(log_path) or ""
            reason = last_reason(text) or (REASON_CRASHED if code not in (0, 2) else None)
            state, report = STATE_BY_CODE.get(code, "error"), parse_report(text)
        except Exception:
            log.exception("наблюдатель запуска %s не смог разобрать итог", run_id)
            code, state, reason, report = None, "error", REASON_CRASHED, {}
        with self._run_lock:
            # on_shutdown забирает активный подпроцесс вместе с правом записать итог.
            if self._child is not None and self._child[0] == run_id:
                self._finish(run_id, state, code, reason, report)
                self._child = None

    def _finish(self, run_id: str, state: str, code: int | None, reason: str | None,
                report: dict[str, str]) -> None:
        # Под _run_lock. Следующий сбор допускается только после сохранения этого итога.
        self._pending_finish = _RunOutcome(run_id, state, code, reason, report, self._now())
        for attempt in range(FINISH_RETRIES):
            try:
                self._flush_finish()
                return
            except Exception:
                log.exception("не удалось закрыть запись %s (попытка %d)", run_id, attempt + 1)
                if attempt + 1 < FINISH_RETRIES:
                    time.sleep(FINISH_PAUSE)

    def _flush_finish(self) -> None:
        """Под _run_lock: сохраняет итог одной попыткой, при ошибке оставляет его в памяти."""
        outcome = self._pending_finish
        if outcome is None:
            return
        self.store.finish(outcome.run_id, outcome.state, outcome.code, outcome.reason,
                          outcome.report, outcome.finished)
        self._pending_finish = None  # отсутствие running также означает, что повтор больше не нужен
        try:  # уборка не должна скрывать итог запуска
            for rid in self.store.prune(RUNS_KEEP):
                (self._logs_dir / f"{rid}.log").unlink(missing_ok=True)
        except Exception:
            log.exception("уборка старых запусков не удалась")

    def _reconcile_finish(self) -> None:
        with self._run_lock:
            self._flush_finish()

    def current(self) -> tuple[RunRecord, list[str]] | None:
        self._reconcile_finish()
        rec = self.store.current()
        if rec is None:
            return None
        text = _read(self._logs_dir / f"{rec.run_id}.log") or ""
        return rec, text.splitlines()[-LOG_TAIL_LINES:]

    def history(self, limit: int = 10) -> list[RunRecord]:
        self._reconcile_finish()
        return self.store.history(limit)

    def log(self, run_id: str) -> str | None:
        self._reconcile_finish()
        if self.store.get(run_id) is None:
            return None
        return _read(self._logs_dir / f"{run_id}.log")

    def on_startup(self) -> int:
        with self._run_lock:
            interrupted = self.store.interrupt_running(self._now())
            self._pending_finish = None
            self._stopping = False
            return interrupted

    def on_shutdown(self) -> None:
        with self._run_lock:
            self._stopping = True
            if self._child is None:
                return
            run_id, proc, watcher = self._child
            interrupted = proc.poll() is None
            if interrupted:
                self._child = None
        if not interrupted:
            watcher.join(STOP_TIMEOUT)
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=STOP_TIMEOUT)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=STOP_TIMEOUT)
        finally:
            with self._run_lock:
                self._finish(run_id, "interrupted", None, REASON_INTERRUPTED, {})
            watcher.join(STOP_TIMEOUT)

    def join_watchers(self, timeout: float = 5) -> None:
        for t in self._watchers:
            t.join(timeout)
        self._watchers = [t for t in self._watchers if t.is_alive()]
