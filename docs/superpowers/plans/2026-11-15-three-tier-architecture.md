# Трёхзвенная архитектура aiDigest — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перевести aiDigest на три приложения — SPA на React+TS (nginx), бэкенд FastAPI с фоновым сбором, PostgreSQL — с образами в GHCR и выкладкой `docker compose pull && up -d`.

**Architecture:** Пайплайн `src/aidigest/` остаётся, но хранит кейсы, учёт кредитов и запуски в Postgres через тонкие репозитории с in-memory двойниками для тестов. Сервисный слой (`aidigest/services/`) содержит всю логику продукта; FastAPI (`aidigest_api`) — тонкие обработчики над ним. Сбор запускает **только бэкенд** — подпроцессом `python -m aidigest run --run-id …` (внутренняя команда, не для человека) внутри своего контейнера; «один сбор» держит частичный уникальный индекс в Postgres.

**Tech Stack:** Python 3.13, FastAPI, uvicorn, SQLAlchemy 2 (Core), psycopg 3, Alembic, itsdangerous; React 18 + TypeScript + Vite, react-router-dom, Vitest + Testing Library; nginx:alpine; postgres:17; GitHub Actions + GHCR.

**Spec:** `docs/superpowers/specs/2026-11-15-three-tier-architecture-design.md`

## Global Constraints

- Вся работа — в ветке `feature/three-tier-architecture`; в `master` — целиком после проверки (Task 15–16).
- Образы: `ghcr.io/larch1k/aidigest-backend`, `ghcr.io/larch1k/aidigest-frontend`; теги `latest` и короткий SHA; публикация только с `master`, через `GITHUB_TOKEN`. Образ БД — официальный `postgres:17`, в GHCR не публикуется.
- Бэкенд — **один контейнер**; при выкладке никаких проверок «идёт ли сбор».
- **Консольного запуска сбора нет.** Сбор стартует только через `RunService.start()` (кнопка или `POST /api/runs`). `python -m aidigest run --run-id ID` — внутренняя команда для подпроцесса; без `--run-id` она отказывается работать. `aidigest export` удаляется; `aidigest eval` остаётся.
- Вход — одна пара `WEB_USERNAME` + `WEB_PASSWORD` (+ `WEB_SECRET_KEY`) из `web.env`.
- `*.env` никогда не читать, не выводить, не коммитить; в образ и CI не попадают.
- Кредиты Tavily на всю работу по плану — **не больше 250**; перед каждым реальным сбором сверить расход (`GET https://api.tavily.com/usage` через `aidigest.usage.fetch_tavily_usage`) с отметкой на старте работы и записать в журнал задачи.
- Тесты не ходят в сеть. Тесты с маркером `pg` ходят в локальный Postgres (`AIDIGEST_TEST_DATABASE_URL`); без переменной они пропускаются, в CI переменная задана всегда.
- Любая цифра в кейсе — со ссылкой на источник; логику извлечения/подтверждения/дедупликации не менять (кроме сохранения подтверждений по одному). Промпты `extract.py`, `confirm.py`, `dedup.py` не трогать — это сбросит кеш LLM.
- Кеш `data/cache/` не удалять — переносится на том бэкенда.
- Комментарии в коде и тексты интерфейса — на русском; формулировки пояснений (флаги, достоверность, поля запросов/источников, справка) переносятся из текущих шаблонов без изменения смысла.
- Ссылки из данных в интерфейсе — только `http(s)`.
- Новые тяжёлые зависимости сверх перечисленных в Tech Stack — не добавлять без обсуждения; UI-фреймворки (MUI, Ant и т.п.) не использовать.

## Review Focus

1. **Вход по `http://<IP>` без HTTPS** — cookie сессии не должна быть `Secure`, пока не задан `AIDIGEST_TRUST_PROXY=1`, иначе вход молча не работает. Тест — Task 7.
2. **Подпроцесс сбора упал или убит, не закрыв запись** — запись не висит «идёт» и кнопка не блокируется: наблюдатель помечает запуск ошибкой. Тест — Task 6.
3. **Свежая установка: пустая база, нет ключа Tavily** — все страницы и эндпоинты отвечают пустыми состояниями, страница запуска показывает учёт кредитов «по нашему учёту», без 500. Тест — Task 7 и Task 10.
4. **Повторный старт контейнера на уже мигрированной БД** — миграции при старте идемпотентны, приложение поднимается. Тест — Task 1.
5. **Отладочные параметры в `POST /api/runs` с мусором** (`budget: -1`, неизвестный уровень, `days: 0`) — 422 с понятным текстом, сбор не стартует и запись запуска не создаётся. Тест — Task 7.

---

## Карта файлов

```
docker-compose.yml            # сервер: db, backend, frontend — только образы
docker-compose.build.yml      # локально: добавляет build: к backend и frontend
docker-compose.dev.yml        # разработка: только db на localhost:5433
docker/dev-init.sql           # создаёт БД aidigest_test
Dockerfile                    # образ бэкенда
alembic.ini
src/aidigest/db/__init__.py
src/aidigest/db/engine.py     # database_url(), make_engine(), migrate()
src/aidigest/db/schema.py     # таблицы SQLAlchemy Core
src/aidigest/db/migrations/   # env.py, script.py.mako, versions/0001_initial.py
src/aidigest/store.py         # Store (Protocol), StoreData, MemoryStore, PgCaseStore (+ CaseStore JSON до Task 16)
src/aidigest/usage.py         # CreditsRepo, MemoryCreditsRepo, PgCreditsRepo, MonthlyUsage(repo, …)
src/aidigest/runstore.py      # RunRecord, RunStore (Pg), MemoryRunStore, parse_report, LogTee
src/aidigest/storage.py       # Storage(cases, credits, runs), open_storage(url)
src/aidigest/backup.py        # backup_db() через pg_dump
src/aidigest/cli.py           # run --run-id (внутренняя, для подпроцесса) и eval
src/aidigest/services/__init__.py
src/aidigest/services/cases.py    # фильтры, headline, ярлыки (из aidigest_web/views.py)
src/aidigest/services/catalog.py  # запросы и источники (из aidigest_web/config_pages.py)
src/aidigest/services/runs.py     # RunService: credits(), start(), current(), history(), log()
src/aidigest_api/__init__.py      # create_app()
src/aidigest_api/__main__.py      # запуск uvicorn, проверки пароля/ключа
src/aidigest_api/auth.py          # LoginLimiter, сессия, client_ip, проверка Origin
src/aidigest_api/routes.py        # /api/*
src/aidigest_api/schemas.py       # ответы API (pydantic)
tests/fakes.py                    # + MemoryStorage-помощники
tests/db/conftest.py, tests/db/test_*.py   # маркер pg
tests/api/conftest.py, tests/api/test_*.py
frontend/                         # Vite + React + TS
frontend/Dockerfile, frontend/nginx.conf
.github/workflows/ci.yml
tools/compare_bases.py            # сравнение старой и новой базы (Task 15)
```

---

### Task 1: Postgres для разработки, схема и миграции

**Files:**
- Create: `docker-compose.dev.yml`, `docker/dev-init.sql`, `alembic.ini`, `src/aidigest/db/__init__.py`, `src/aidigest/db/engine.py`, `src/aidigest/db/schema.py`, `src/aidigest/db/migrations/env.py`, `src/aidigest/db/migrations/script.py.mako`, `src/aidigest/db/migrations/versions/0001_initial.py`
- Modify: `pyproject.toml` (dependencies + маркер `pg`), `.gitignore`
- Test: `tests/db/conftest.py`, `tests/db/test_schema.py`

**Interfaces:**
- Produces:
  - `database_url() -> str` — `DATABASE_URL` из окружения, иначе `postgresql+psycopg://aidigest:aidigest@localhost:5433/aidigest`.
  - `make_engine(url: str | None = None) -> sqlalchemy.Engine` (`pool_pre_ping=True`).
  - `migrate(engine: Engine) -> None` — `alembic upgrade head` программно; путь к миграциям — относительно пакета (работает и в образе, и из `.venv`).
  - `schema.metadata` и таблицы:
    - `cases(id text PK, level text NOT NULL, first_seen date NOT NULL, updated date NOT NULL, data jsonb NOT NULL)`
    - `processed_urls(url text PK, added timestamptz NOT NULL DEFAULT now())`
    - `credits(month text PK, spent double precision NOT NULL)`
    - `runs(id text PK, state text NOT NULL, started timestamptz NOT NULL, finished timestamptz, exit_code int, reason text, params jsonb NOT NULL DEFAULT '{}', log text NOT NULL DEFAULT '')` — `params`: отладочные параметры запуска (пусто — обычный сбор)
    - частичный уникальный индекс `runs_one_running ON runs ((true)) WHERE state = 'running'`.
  - Фикстура `pg_engine` (scope session): берёт `AIDIGEST_TEST_DATABASE_URL`, при отсутствии — `pytest.skip("нет AIDIGEST_TEST_DATABASE_URL")`; пересоздаёт схему `public` и вызывает `migrate`. Фикстура `pg` (function): `TRUNCATE cases, processed_urls, credits, runs` и отдаёт engine.

- [ ] **Step 1: Добавить зависимости и маркер**

В `pyproject.toml` dependencies: `sqlalchemy>=2`, `psycopg[binary]>=3.2`, `alembic`. Extra `api = ["fastapi", "uvicorn", "itsdangerous", "httpx"]` (httpx — для TestClient). `[tool.pytest.ini_options] markers = ["pg: тест ходит в Postgres (AIDIGEST_TEST_DATABASE_URL)"]`. Установить: `.venv/Scripts/python -m pip install -e ".[dev,web,api]"`.

- [ ] **Step 2: Dev-компоуз**

`docker-compose.dev.yml`: сервис `db`, образ `postgres:17`, `POSTGRES_USER/PASSWORD/DB = aidigest`, порт `127.0.0.1:5433:5432`, том `aidigest-dev-pg`, `docker/dev-init.sql` → `/docker-entrypoint-initdb.d/` с `CREATE DATABASE aidigest_test;`. Запуск: `docker compose -f docker-compose.dev.yml up -d`. Ожидание: `docker compose -f docker-compose.dev.yml ps` показывает `db` в `running`.

- [ ] **Step 3: Написать падающие тесты**

```python
# tests/db/test_schema.py
import pytest
from sqlalchemy import inspect, text
pytestmark = pytest.mark.pg

def test_tables_exist(pg):
    names = set(inspect(pg).get_table_names())
    assert {"cases", "processed_urls", "credits", "runs"} <= names

def test_migrate_is_idempotent(pg):
    from aidigest.db.engine import migrate
    migrate(pg); migrate(pg)   # второй старт контейнера не падает

def test_only_one_running_run(pg):
    ins = text("INSERT INTO runs (id, state, started) VALUES (:id, 'running', now())")
    with pg.begin() as c:
        c.execute(ins, {"id": "a"})
    with pytest.raises(Exception):
        with pg.begin() as c:
            c.execute(ins, {"id": "b"})
```

- [ ] **Step 4: Убедиться, что падают**

Run: `$env:AIDIGEST_TEST_DATABASE_URL="postgresql+psycopg://aidigest:aidigest@localhost:5433/aidigest_test"; .venv/Scripts/python -m pytest tests/db -q`
Expected: FAIL — `ModuleNotFoundError: aidigest.db`.

- [ ] **Step 5: Реализовать engine, schema, миграцию `0001_initial` и фикстуры** (см. Interfaces; миграция создаёт ровно эти таблицы и индекс).

- [ ] **Step 6: Тесты проходят** — та же команда, Expected: `3 passed`. Без переменной: `3 skipped`. Весь набор `.venv/Scripts/python -m pytest -q` зелёный.

- [ ] **Step 7: Commit** — `git add ... && git commit -m "feat(db): Postgres для разработки, схема и миграции"`

---

### Task 2: Хранилище кейсов в Postgres и подтверждения по одному

**Files:**
- Modify: `src/aidigest/store.py`, `src/aidigest/pipeline.py:19,66,139,147-158`
- Modify: `tests/test_pipeline.py` (тесты цикла — на `MemoryStore`)
- Test: `tests/test_store.py`, `tests/db/test_pg_store.py`, `tests/test_pipeline.py`

**Interfaces:**
- Produces (в `aidigest.store`):
  - `class Store(Protocol): def load(self) -> StoreData; def save(self, data: StoreData) -> None`
  - `class MemoryStore` — хранит глубокую копию (`model_copy(deep=True)`), чтобы тесты ловили «забыли save».
  - `class PgCaseStore(engine)`: `load()` читает все кейсы (`Case.model_validate(data)`) и URL; `save(data)` — **одна транзакция**: upsert всех кейсов (`INSERT … ON CONFLICT (id) DO UPDATE SET level, first_seen, updated, data`), `INSERT processed_urls … ON CONFLICT DO NOTHING`. Кейсы не удаляет (пайплайн их не удаляет). `data` — `case.model_dump(mode="json")`.
  - `PgCaseStore.updated_at() -> datetime | None` — `max(updated)`/время последней записи для «дата обновления базы» (берётся `max(processed_urls.added)`).
  - `Deps.store: Store`.
  - JSON `CaseStore` остаётся без изменений до Task 16 (на нём живёт старый `aidigest_web`).

- [ ] **Step 1: Падающие тесты**

```python
# tests/db/test_pg_store.py  (pytestmark = pytest.mark.pg)
def test_roundtrip_and_upsert(pg, make_case):
    s = PgCaseStore(pg)
    s.save(StoreData([make_case(id="c1", title="А")], {"https://x.ru/1"}))
    d = s.load(); d.cases[0].title = "Б"; d.cases.append(make_case(id="c2"))
    s.save(d)
    again = s.load()
    assert {c.id: c.title for c in again.cases} == {"c1": "Б", "c2": "Умные светофоры"}
    assert again.processed_urls == {"https://x.ru/1"}

def test_empty_db_loads_empty(pg):
    assert PgCaseStore(pg).load() == StoreData()

def test_save_is_atomic(pg, make_case, monkeypatch):
    s = PgCaseStore(pg)
    bad = make_case(id="c2"); object.__setattr__(bad, "level", None)  # сломает INSERT
    with pytest.raises(Exception):
        s.save(StoreData([make_case(id="c1"), bad], {"https://x.ru/1"}))
    assert s.load() == StoreData()   # ни кейса, ни URL
```

```python
# tests/test_pipeline.py — новый тест
def test_confirmations_saved_one_by_one(registry, case_reply):
    """Если подтверждение второго кейса падает, результат первого уже в базе."""
    # собрать базу с двумя кейсами в очереди подтверждения; FakeSearch отдаёт подтверждающую
    # статью для первого и бросает KeyboardInterrupt на втором; после pytest.raises(KeyboardInterrupt)
    # store.load() содержит у первого кейса confirmation_attempts == 1
```

- [ ] **Step 2: Убедиться, что падают** — `pytest tests/db/test_pg_store.py tests/test_pipeline.py -q` → FAIL (`PgCaseStore` нет; подтверждение не сохранено).

- [ ] **Step 3: Реализовать** `Store`, `MemoryStore`, `PgCaseStore`; в `run_cycle` после каждого `confirm_case(...)` (и в ветках `except`, кроме `BudgetExceeded`) — `deps.store.save(data)`; финальный `save` оставить. Тесты `tests/test_pipeline.py`, которые строят `Deps` с `CaseStore(tmp_path / ...)`, перевести на `MemoryStore()`; тесты `cmd_*` пока не трогать.

- [ ] **Step 4: Тесты проходят** — `.venv/Scripts/python -m pytest -q` (с `AIDIGEST_TEST_DATABASE_URL`) → всё зелёное.

- [ ] **Step 5: Commit** — `feat(store): кейсы в Postgres, подтверждения сохраняются по одному`

---

### Task 3: Учёт кредитов в Postgres

**Files:**
- Modify: `src/aidigest/usage.py`, `src/aidigest_web/runs.py` (`_local`: `MonthlyUsage(JsonCreditsRepo(path), …)`)
- Test: `tests/test_usage.py`, `tests/db/test_pg_credits.py`

**Interfaces:**
- Produces:
  - `class CreditsRepo(Protocol): def get(self, month: str) -> float; def add(self, month: str, credits: float) -> None`
  - `MemoryCreditsRepo()`, `PgCreditsRepo(engine)` (`add` — `INSERT … ON CONFLICT (month) DO UPDATE SET spent = credits.spent + excluded.spent`), `JsonCreditsRepo(path)` (формат `credits.json`, удаляется в Task 16).
  - `MonthlyUsage(repo: CreditsRepo, limit: float, warn_share: float = 0.8)` — методы `spent/remaining/cap/record/sync/warning` с прежним поведением.

- [ ] **Step 1: Переписать `tests/test_usage.py` на `MemoryCreditsRepo`** (те же утверждения, что сейчас для `tmp_path`), добавить `tests/db/test_pg_credits.py::test_add_accumulates_per_month` (`add("2026-11", 3); add("2026-11", 2.5); get("2026-11") == 5.5; get("2026-12") == 0`).
- [ ] **Step 2: FAIL** — `pytest tests/test_usage.py tests/db -q`.
- [ ] **Step 3: Реализовать** репозитории и новую сигнатуру `MonthlyUsage`; поправить `aidigest_web/runs.py` и `cli.py` (`MonthlyUsage(JsonCreditsRepo(_data_dir() / "credits.json"), …)` — временно, до Task 5).
- [ ] **Step 4: PASS** — весь набор зелёный.
- [ ] **Step 5: Commit** — `feat(usage): учёт кредитов через репозиторий, реализация для Postgres`

---

### Task 4: Запуски в Postgres: история и лог

**Files:**
- Create: `src/aidigest/runstore.py`
- Test: `tests/test_runstore.py` (MemoryRunStore + parse_report + LogTee), `tests/db/test_pg_runstore.py`

**Interfaces:**
- Produces (`aidigest.runstore`):
  - Константы (перенос из `aidigest_web/runs.py`): `STATE_LABEL`, `STATE_BY_CODE = {0: "ok", 2: "limit"}`, `REPORT_PREFIXES`, `REASON_INTERRUPTED = "Сбор прерван перезапуском сервера. Кейсы, которые он успел сохранить, уже в базе."`, `REASON_CRASHED = "Сборщик завершился аварийно — сообщите команде разработки."`.
  - `parse_report(log_text: str) -> dict[str, str]` — перенос как есть.
  - `@dataclass RunRecord(run_id: str, state: str, started: datetime, finished: datetime | None, exit_code: int | None, reason: str | None, params: dict, log: str)`; свойства `label`, `minutes`, `report` (= `parse_report(log)`), метод `tail(lines: int = 30) -> list[str]`.
  - `class AlreadyRunning(Exception)`.
  - `class RunStore` (Postgres, `RunStore(engine)`) и `class MemoryRunStore` с одинаковыми методами:
    - `create(run_id: str, started: datetime, params: dict | None = None) -> None` — state `running`; нарушение `runs_one_running` → `AlreadyRunning`.
    - `append_log(run_id: str, chunk: str) -> None` — `log = log || :chunk`.
    - `finish(run_id: str, state: str, exit_code: int | None, reason: str | None, finished: datetime) -> bool` — только если запись ещё `running`; `True`, если запись закрыта этим вызовом.
    - `interrupt_running(now: datetime) -> int` — все `running` → `interrupted` с `REASON_INTERRUPTED`; число помеченных.
    - `current() -> RunRecord | None`, `get(run_id) -> RunRecord | None`, `history(limit: int = 10) -> list[RunRecord]` (по `started` убыв., включая текущий), `prune(keep: int = 100) -> int`.
  - `class LogTee(runs, run_id, flush_seconds: float = 2.0)` — контекстный менеджер: подменяет `sys.stdout`/`sys.stderr` обёртками, которые пишут в исходный поток и копят текст; фоновый поток каждые `flush_seconds` и при выходе вызывает `append_log`. Ошибка записи в БД печатается в исходный stderr один раз и не роняет сбор. Возвращает объект с `last_reason() -> str | None` (последняя строка `Причина: …` без префикса).

- [ ] **Step 1: Падающие тесты** (оба варианта хранилища через параметризацию фикстуры `runs`: `MemoryRunStore()` всегда, `RunStore(pg)` — с маркером `pg`)

```python
def test_second_create_while_running_fails(runs):
    runs.create("r1", NOW)
    with pytest.raises(AlreadyRunning):
        runs.create("r2", NOW)

def test_interrupt_running(runs):
    runs.create("r1", NOW)
    assert runs.interrupt_running(NOW) == 1
    r = runs.get("r1"); assert r.state == "interrupted" and r.reason == REASON_INTERRUPTED
    runs.create("r2", NOW)          # после прерывания новый запуск возможен

def test_finish_only_running(runs):
    runs.create("r1", NOW)
    assert runs.finish("r1", "ok", 0, None, NOW) is True
    assert runs.finish("r1", "error", 1, "x", NOW) is False and runs.get("r1").state == "ok"

def test_log_report_tail_params(runs):
    runs.create("r1", NOW, {"budget": 5})
    runs.append_log("r1", "Кейсов новых: 3\n"); runs.append_log("r1", "строка\n")
    r = runs.get("r1")
    assert r.report == {"Кейсов новых": "3"} and r.tail(1) == ["строка"] and r.params == {"budget": 5}

def test_logtee_copies_output_and_reason(runs, capsys):
    runs.create("r1", NOW)
    with LogTee(runs, "r1", flush_seconds=0.05) as tee:
        print("привет"); print("Причина: нет ключей", file=sys.stderr)
    assert "привет" in runs.get("r1").log and tee.last_reason() == "нет ключей"
    assert "привет" in capsys.readouterr().out
```

Плюс `test_parse_report_*` — перенести тесты `parse_report` из `tests/web/test_runs.py`.

- [ ] **Step 2: FAIL** — `pytest tests/test_runstore.py tests/db/test_pg_runstore.py -q`.
- [ ] **Step 3: Реализовать** `runstore.py` по Interfaces.
- [ ] **Step 4: PASS** (с и без `AIDIGEST_TEST_DATABASE_URL`).
- [ ] **Step 5: Commit** — `feat(runs): запуски и лог в Postgres`

---

### Task 5: Внутренняя команда сбора на новом хранилище, резервная копия

**Files:**
- Create: `src/aidigest/storage.py`, `src/aidigest/backup.py`
- Modify: `src/aidigest/cli.py`, `src/aidigest/housekeeping.py` (убрать `backup_cases`; `prune_cache`, `keep_newest`, `BACKUPS_KEEP` остаются)
- Delete: `src/aidigest/runlock.py`, `tests/test_runlock.py`
- Modify: `tests/test_pipeline.py` (тесты `cmd_*`), `tests/conftest.py`, `tests/fakes.py`
- Test: `tests/test_cli_run.py`, `tests/test_backup.py`

**Interfaces:**
- Consumes: `PgCaseStore`, `PgCreditsRepo`, `RunStore`, `LogTee` (Tasks 2–4).
- Produces:
  - `@dataclass Storage(cases: Store, credits: CreditsRepo, runs: RunStore | MemoryRunStore, database_url: str | None)`; `open_storage(url: str | None = None) -> Storage` (Postgres, вызывает `migrate`); `memory_storage() -> Storage` (в `tests/fakes.py`).
  - В `cli.py`: модульная функция `_storage() -> Storage` (по умолчанию `open_storage()`); фикстура `storage` в `tests/conftest.py` подменяет её `monkeypatch.setattr("aidigest.cli._storage", lambda: st)`.
  - `aidigest run --run-id ID [--budget N] [--levels …] [--days N] [--offline] [--first-run]` — **внутренняя команда**: запись запуска `ID` уже создана бэкендом. Без `--run-id` — печать `Причина: сбор запускается с сайта (кнопка «Запустить сбор») или через POST /api/runs.` и выход 1, без записи в базу. Поток:
    1. `with LogTee(st.runs, run_id) as tee:` — `prune_cache(data_dir)`, `backup_db(...)`, затем прежняя логика `_run_locked` (без `run_lock`; учёт кредитов — `MonthlyUsage(st.credits, …)`, `Deps.store = st.cases`).
    2. `st.runs.finish(run_id, STATE_BY_CODE.get(code, "error"), code, tee.last_reason(), now)`; `st.runs.prune()`.
    Коды выхода 0/1/2 и строки «Причина: …» — как сейчас (код 3 «уже идёт» больше не нужен — это проверяет бэкенд). Если не заданы ни `--budget`, ни `--first-run`, а в базе нет ни одного кейса, бюджет — `first_run_budget` (первый сбор на свежей установке получает 100 кредитов).
  - Команда `export` удаляется; `eval` — без изменений.
  - `backup_db(database_url: str, backups_dir: Path, now: datetime, keep: int = BACKUPS_KEEP, run=subprocess.run) -> Path | None` — `pg_dump -Fc -f <backups>/aidigest_<ГГГГ-ММ-ДД_ЧЧММСС>.dump`; URL переводится в libpq-вид (без `+psycopg`), пароль — через `PGPASSWORD` в env, не в аргументах; нет `pg_dump` в PATH → печать «Резервная копия пропущена: нет pg_dump» и `None`; хранит `keep` последних.

- [ ] **Step 1: Перевести тесты `cmd_*` в `tests/test_pipeline.py` на фикстуру `storage`** и `--run-id` (утверждения прежние: коды выхода, строки «Причина», учёт кредитов — теперь `storage.credits.get(month)`); удалить `test_cli_run_refuses_when_locked` и `test_cli_export_offline`. Добавить в `tests/test_cli_run.py`:

```python
def test_run_without_run_id_refuses(storage, capsys):
    assert main(["run", "--offline", "--budget", "0"]) == 1
    assert "Причина: сбор запускается с сайта" in capsys.readouterr().out
    assert storage.runs.history() == []

def test_run_finishes_given_record_with_report(storage):
    storage.runs.create("web-1", NOW)
    assert main(["run", "--offline", "--budget", "0", "--run-id", "web-1"]) == 0
    r = storage.runs.get("web-1"); assert r.state == "ok" and "Кейсов новых" in r.report

def test_run_uses_first_run_budget_on_empty_base(storage, capsys): ...   # в выводе бюджет 100
def test_run_error_closes_record_with_reason(storage, monkeypatch): ...  # run_cycle бросает → state "error", reason из «Причина: …»
```

`tests/test_backup.py`: команда содержит `-Fc` и путь в `backups_dir`, пароль только в `env["PGPASSWORD"]` и не в аргументах; при `FileNotFoundError` — `None`; остаётся `keep` файлов.

- [ ] **Step 2: FAIL** — `pytest tests/test_pipeline.py tests/test_cli_run.py tests/test_backup.py -q`.
- [ ] **Step 3: Реализовать** `storage.py`, `backup.py`, новый `cmd_run`; удалить `cmd_export`, `runlock.py`.
- [ ] **Step 4: PASS** — весь набор; ручная проверка против dev-БД: создать запись (`python -c "…RunStore(make_engine()).create('t1', datetime.now())"`), затем `$env:DATABASE_URL="postgresql+psycopg://aidigest:aidigest@localhost:5433/aidigest"; .venv/Scripts/python -m aidigest run --run-id t1 --offline --budget 0` → код 0, запись `t1` в состоянии `ok` с логом.
- [ ] **Step 5: Commit** — `feat(cli): внутренняя команда сбора на Postgres, pg_dump перед сбором`

---

### Task 6: Сервисный слой

**Files:**
- Create: `src/aidigest/services/__init__.py`, `services/cases.py`, `services/catalog.py`, `services/runs.py`
- Modify: `src/aidigest_web/views.py`, `src/aidigest_web/config_pages.py` — реэкспорт из сервисов (чтобы старый сайт работал до Task 16)
- Test: `tests/services/test_cases.py` (перенос `tests/web/test_views.py` + новые), `tests/services/test_catalog.py` (перенос логики из `tests/web/test_config_pages.py`), `tests/services/test_runs.py`

**Interfaces:**
- Produces:
  - `services.cases`: всё из `aidigest_web/views.py` без изменений имён (`filter_cases`, `headline`, `best_reliability`, `reliability_rank`, `FLAG_HELP`, `STATUS_LABEL`, `STATUS_CLASS`, `RELIABILITY_*`, `NO_RATED`, `DOUBTFUL`) плюс
    - `@dataclass CaseFilter(q: str = "", level: str = "", status: str = "", with_metrics: bool = True, hide_doubtful: bool = False, reliability: str = "")`
    - `class CaseService(store: Store)`: `list(f: CaseFilter) -> tuple[list[Case], int]` (отфильтрованные, всего); `get(case_id: str) -> Case | None`; `export_xlsx() -> bytes` (через `export_xlsx` во временной папке, без остатков файлов); `updated_at() -> datetime | None` (если у store есть `updated_at`).
  - `services.catalog`: `ANY_RF_LEVEL`, `ANY_RF_LABEL`, `level_label`, `group_queries`, `filter_sources` (перенос), `class CatalogService(config_dir: Path)`: `queries() -> tuple[list[tuple[Level, list[QuerySpec]]], int, int, str | None]` (группы, всего, `freshness_days`, ошибка), `sources(level: str = "", reliability: str = "") -> tuple[list[SourceInfo], int, str | None]`. Ошибки чтения YAML — текст ошибки, не исключение.
  - `services.runs`:
    - `class MonthExhausted(Exception)`; `AlreadyRunning` — из `aidigest.runstore`.
    - `@dataclass RunParams(budget: float | None = None, levels: list[Level] | None = None, days: int | None = None, offline: bool = False)`; `to_argv() -> list[str]` (`--budget`, `--levels` через запятую, `--days`, `--offline`); `as_dict() -> dict` (только заданные поля, для `runs.params`).
    - `class RunService(storage: Storage, project_root: Path, settings_path: Path, tavily_token: str | None, popen=subprocess.Popen, now=datetime.now)`:
      - `credits() -> dict` — `{"spent", "limit", "remaining", "source": "tavily"|"local", "run_budget"}`; Tavily-ответ кешируется 60 с (перенос `RunManager.credits/_tavily/_local`).
      - `start(params: RunParams | None = None) -> str` — `credits()["remaining"] <= 0` и не `offline` → `MonthExhausted`; `run_id = now().strftime("%Y%m%d-%H%M%S")`; `create(run_id, now, params.as_dict())` (→ `AlreadyRunning`); `popen([sys.executable, "-m", "aidigest", "run", "--run-id", run_id, *params.to_argv()], cwd=project_root, env={…, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"})`; если `popen` бросил — `finish(run_id, "error", None, "Не удалось запустить сбор.")` и исключение дальше. Поток-наблюдатель ждёт процесс; если после выхода запись всё ещё `running` — `finish(run_id, "error", code, REASON_CRASHED)`. Возвращает `run_id`.
      - `current() -> RunRecord | None`, `history(limit=10)`, `log(run_id) -> str | None`.
      - `on_startup() -> int` — `interrupt_running(now)`: бэкенд только что стартовал, других источников сбора нет — всё «идущее» оборвано перезапуском.
      - `join_watchers(timeout: float = 5) -> None` — для тестов.

- [ ] **Step 1: Падающие тесты** (на `memory_storage()` и фейковом `popen`)

```python
def test_start_spawns_cli_with_run_id_and_params(svc, popen_calls):
    rid = svc.start(RunParams(budget=5, levels=[Level.SVERDLOVSK], offline=True))
    argv = popen_calls[0]
    assert argv[3:6] == ["run", "--run-id", rid]
    assert ["--budget", "5"] == argv[argv.index("--budget"):argv.index("--budget") + 2]
    assert "--offline" in argv and svc.current().params == {"budget": 5, "levels": ["Свердловская область"], "offline": True}

def test_start_twice_raises(svc):
    svc.start()
    with pytest.raises(AlreadyRunning): svc.start()

def test_start_refuses_when_month_exhausted(svc_exhausted):
    with pytest.raises(MonthExhausted): svc_exhausted.start()

def test_crashed_child_marks_error(svc_child_exits_1):                 # Review Focus 2
    rid = svc_child_exits_1.start(); svc_child_exits_1.join_watchers()
    r = svc_child_exits_1.storage.runs.get(rid); assert r.state == "error" and r.reason == REASON_CRASHED
    svc_child_exits_1.start()                                          # кнопка снова доступна

def test_popen_failure_closes_record(svc_popen_raises):
    with pytest.raises(OSError): svc_popen_raises.start()
    assert svc_popen_raises.current() is None

def test_on_startup_interrupts_left_running(svc):
    svc.storage.runs.create("old", NOW)
    assert svc.on_startup() == 1 and svc.storage.runs.get("old").state == "interrupted"

def test_credits_local_when_no_tavily(svc):                             # Review Focus 3
    c = svc.credits(); assert c["source"] == "local" and c["spent"] == 0 and c["limit"] == 1000

def test_case_service_filters_and_counts(make_case):
    st = MemoryStore(); st.save(StoreData([make_case(id="a"), make_case(id="b", metrics=[])], set()))
    shown, total = CaseService(st).list(CaseFilter())
    assert [c.id for c in shown] == ["a"] and total == 2

def test_export_returns_xlsx_bytes(make_case):
    ... assert CaseService(st).export_xlsx()[:2] == b"PK"
```

- [ ] **Step 2: FAIL** — `pytest tests/services -q`.
- [ ] **Step 3: Реализовать**; `aidigest_web/views.py` и `config_pages.py` импортируют перенесённое из сервисов.
- [ ] **Step 4: PASS** — весь набор.
- [ ] **Step 5: Commit** — `feat(services): сервисный слой кейсов, справочников и запусков`

---

### Task 7: HTTP API на FastAPI

**Files:**
- Create: `src/aidigest_api/__init__.py`, `__main__.py`, `auth.py`, `routes.py`, `schemas.py`
- Modify: `src/aidigest/creds.py` (`WEB_KEYS = ("WEB_USERNAME", "WEB_PASSWORD", "WEB_SECRET_KEY")`)
- Test: `tests/api/conftest.py`, `tests/api/test_auth.py`, `tests/api/test_cases.py`, `tests/api/test_runs.py`, `tests/api/test_catalog.py`

**Interfaces:**
- Consumes: `CaseService`, `CatalogService`, `RunService`, `Storage` (Task 6, 5).
- Produces:
  - `create_app(storage: Storage, *, username: str | None, password: str | None, secret_key: str | None, trust_proxy: bool = False, config_dir: Path | None = None, run_service: RunService | None = None, migrate_on_start: bool = True) -> FastAPI`. В lifespan: `migrate` (если `migrate_on_start` и Postgres), `run_service.on_startup()`.
  - Сессия: `SessionMiddleware(secret_key, session_cookie="aidigest_session", same_site="strict", https_only=trust_proxy, max_age=14 * 24 * 3600)`.
  - Без `password` вход отключён (локальная разработка), но запросы с `Host` не из `localhost/127.0.0.1/[::1]` → 400 (перенос `guard_requests`).
  - POST-запросы: `Sec-Fetch-Site` не `same-origin`/`none` → 403; `Origin` есть и его хост ≠ `Host` → 403.
  - `client_ip(request, trust_proxy) -> str`: без `trust_proxy` — заголовок `X-Real-IP` (его ставит nginx), иначе `request.client.host`; с `trust_proxy` — предпоследний элемент `X-Forwarded-For` (клиент перед Caddy), если элементов ≥ 2, иначе `X-Real-IP`.
  - `LoginLimiter` — перенос из `aidigest_web/auth.py` (10 неудач за 600 с; текст `BLOCKED_TEXT`).
  - Эндпоинты (все, кроме `/healthz`, `/api/login`, `/api/me`, требуют сессию → 401 `{"detail": "нужен вход"}`):

    | Метод и путь | Ответ |
    |---|---|
    | `GET /healthz` | `ok` (text/plain), без БД |
    | `POST /api/login` `{username, password}` | 204 + cookie; 401 `{"detail": "Неверный логин или пароль"}`; 429 `{"detail": BLOCKED_TEXT}`; сравнение `hmac.compare_digest` для обоих полей |
    | `POST /api/logout` | 204 |
    | `GET /api/me` | `{"authenticated": bool, "login_required": bool}` |
    | `GET /api/meta` | `{"levels": [...], "statuses": [{"value","label","class"}], "reliability": [{"value","label"}], "flag_help": {flag: [что, что делать]}}` |
    | `GET /api/cases?q&level&status&metrics=1&doubtful=0&reliability` | `{"total", "updated": iso\|null, "cases": [CaseRow]}`; `CaseRow`: `id, title, level, country, region, organization, industry, stage, first_seen, status, status_label, status_class, headline, headline_unverified, reliability, reliability_label, reliability_class, flags` |
    | `GET /api/cases/{id}` | `Case.model_dump(mode="json")` + `status_label`, `status_class`, `reliability_label`; 404 `{"detail": "Кейс не найден"}` |
    | `GET /api/export.xlsx` | файл `aidigest_cases_<ГГГГ-ММ-ДД>.xlsx` |
    | `GET /api/credits` | `RunService.credits()` |
    | `GET /api/runs/current` | `{"running": false}` или `{"running": true, "run_id", "started", "minutes", "tail": [...]}` |
    | `POST /api/runs` (тело необязательно: `{"budget"?: число > 0, "levels"?: [уровень], "days"?: целое ≥ 1, "offline"?: bool}` → `RunParams`) | 202 `{"run_id"}`; 422 при неверных полях (запуск не создаётся); 409 `{"detail": "Сбор уже идёт — дождитесь, пока он закончится."}`; 409 `{"detail": "Лимит кредитов Tavily исчерпан — новый сбор возможен после пополнения лимита."}` |
    | `GET /api/runs?limit=10` | `[{"run_id","state","label","started","finished","minutes","exit_code","reason","report","params"}]` |
    | `GET /api/runs/{id}/log` | text/plain; 404 |
    | `GET /api/queries` | `{"groups": [{"level", "queries": [...]}], "total", "freshness_days", "error"}` |
    | `GET /api/sources?level&reliability` | `{"sources": [...], "total", "error", "level_options", "reliability_options"}` |
  - `__main__`: `python -m aidigest_api [--host 127.0.0.1] [--port 8000]`; ключи `web.env` через `load_creds(ROOT / "web.env", WEB_KEYS)`; не-локальный хост без `WEB_PASSWORD`/`WEB_USERNAME` → выход 2 с текстом, без `WEB_SECRET_KEY` → выход 2 (тексты — по образцу `aidigest_web/__main__.py`); `AIDIGEST_TRUST_PROXY=1` → `trust_proxy`. Запуск `uvicorn.run(app, host, port, proxy_headers=False)`. Сбор стартует через `RunService` с `project_root=ROOT`, `tavily_token` из `tavily.env`/окружения.

- [ ] **Step 1: Падающие тесты** (TestClient, `memory_storage()`, фейковый `popen`, `migrate_on_start=False`)

```python
def test_api_requires_login(client):
    assert client.get("/api/cases").status_code == 401

def test_login_sets_non_secure_cookie_without_proxy(client):        # Review Focus 1
    r = client.post("/api/login", json={"username": "u", "password": "p"})
    assert r.status_code == 204
    cookie = r.headers["set-cookie"].lower()
    assert "aidigest_session=" in cookie and "secure" not in cookie and "samesite=strict" in cookie

def test_login_cookie_secure_with_trust_proxy(proxy_client):
    r = proxy_client.post("/api/login", json={"username": "u", "password": "p"})
    assert "secure" in r.headers["set-cookie"].lower()

def test_wrong_password_then_block(client):
    for _ in range(10): client.post("/api/login", json={"username": "u", "password": "x"})
    assert client.post("/api/login", json={"username": "u", "password": "p"}).status_code == 429

def test_limiter_uses_real_ip_header(client):
    for _ in range(10):
        client.post("/api/login", json={"username": "u", "password": "x"}, headers={"X-Real-IP": "1.1.1.1"})
    ok = client.post("/api/login", json={"username": "u", "password": "p"}, headers={"X-Real-IP": "2.2.2.2"})
    assert ok.status_code == 204

def test_cross_site_post_rejected(authed):
    assert authed.post("/api/runs", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert authed.post("/api/runs", headers={"Origin": "http://evil.test"}).status_code == 403

def test_empty_base_everything_answers(authed):                      # Review Focus 3
    assert authed.get("/api/cases").json() == {"total": 0, "updated": None, "cases": []}
    assert authed.get("/api/runs/current").json() == {"running": False}
    assert authed.get("/api/runs").json() == []
    assert authed.get("/api/credits").json()["source"] == "local"
    assert authed.get("/api/export.xlsx").status_code == 200

def test_case_list_filters_and_detail(authed_with_cases): ...       # metrics=0 показывает кейс без цифр; 404 на неизвестный id
def test_start_run_and_conflict(authed): ...                         # 202, затем 409 с текстом «Сбор уже идёт…»
def test_start_run_passes_debug_params(authed, popen_calls): ...      # {"budget": 5, "levels": ["Свердловская область"], "offline": true} → в argv подпроцесса

@pytest.mark.parametrize("body", [{"budget": -1}, {"levels": ["марс"]}, {"days": 0}])
def test_start_run_rejects_bad_params(authed, body):                 # Review Focus 5
    assert authed.post("/api/runs", json=body).status_code == 422
    assert authed.get("/api/runs").json() == []
def test_queries_and_sources(authed): ...                            # реальные config/*.yaml: total > 0, error is None
def test_foreign_host_rejected_without_password(open_client):
    assert open_client.get("/api/cases", headers={"Host": "evil.test"}).status_code == 400
```

- [ ] **Step 2: FAIL** — `pytest tests/api -q`.
- [ ] **Step 3: Реализовать** `aidigest_api` по Interfaces.
- [ ] **Step 4: PASS** — весь набор; ручная проверка: `.venv/Scripts/python -m aidigest_api --port 8001` и `curl http://localhost:8001/healthz` → `ok`; `curl http://localhost:8001/api/cases` → JSON (вход отключён без пароля).
- [ ] **Step 5: Commit** — `feat(api): HTTP API на FastAPI поверх сервисного слоя`

---

### Task 8: Образ бэкенда и compose для сервера

**Files:**
- Modify: `Dockerfile`, `.dockerignore`, `tools/lock_deps.sh` (extra `[api,dev]` вместо `[web,dev]`), `requirements.lock`, `.env.example`
- Replace: `docker-compose.yml`
- Create: `docker-compose.build.yml`
- Delete: `deploy.sh` (заменяется командами в `docs/deploy.md`, Task 14)

**Interfaces:**
- Produces:
  - Образ бэкенда: `python:3.13-slim`, `apt-get install tzdata postgresql-client` (проверить `pg_dump --version` ≥ 17 — иначе добавить репозиторий PGDG), `TZ=Asia/Yekaterinburg`, `PYTHONPATH=/app/src`, `AIDIGEST_DATA_DIR=/data`, `EXPOSE 8000`, `CMD ["python", "-m", "aidigest_api", "--host", "0.0.0.0", "--port", "8000"]`. Конфиги `config/`, `eval/` — в образе.
  - `docker-compose.yml` (только образы):
    - `db`: `postgres:17`, `POSTGRES_USER=aidigest`, `POSTGRES_DB=aidigest`, `POSTGRES_PASSWORD=${POSTGRES_PASSWORD:?задайте POSTGRES_PASSWORD в .env}`, том `${AIDIGEST_DATA_HOST:-/srv/aidigest/data}/postgres:/var/lib/postgresql/data`, healthcheck `pg_isready -U aidigest`, порт не публикуется.
    - `backend`: `ghcr.io/larch1k/aidigest-backend:${AIDIGEST_VERSION:-latest}`, `user: "${AIDIGEST_UID:-1000}:${AIDIGEST_GID:-1000}"`, `DATABASE_URL=postgresql+psycopg://aidigest:${POSTGRES_PASSWORD}@db:5432/aidigest`, `AIDIGEST_TRUST_PROXY=${AIDIGEST_TRUST_PROXY:-0}`, том `${AIDIGEST_DATA_HOST:-/srv/aidigest/data}/backend:/data`, `env_file` — `web.env`, `tavily.env`, `litellm.env` из `${AIDIGEST_SECRETS:-/srv/aidigest/secrets}` (`required: false`), `depends_on: db: condition: service_healthy`, healthcheck на `http://localhost:8000/healthz`, `init: true`, порт не публикуется.
    - `frontend`: `ghcr.io/larch1k/aidigest-frontend:${AIDIGEST_VERSION:-latest}`, `ports: "${AIDIGEST_HTTP_PORT:-80}:80"`, `depends_on: backend`.
    - Всем: `restart: unless-stopped`, логи json-file `10m × 3`.
  - `docker-compose.build.yml`: `backend.build: .`, `frontend.build: ./frontend` (для локальной сборки: `docker compose -f docker-compose.yml -f docker-compose.build.yml build`).
  - `.env.example`: `AIDIGEST_VERSION=latest`, `AIDIGEST_DATA_HOST`, `AIDIGEST_SECRETS`, `AIDIGEST_HTTP_PORT`, `AIDIGEST_UID/GID`, `POSTGRES_PASSWORD=` (комментарий: только буквы и цифры, например `openssl rand -hex 24`), `AIDIGEST_TRUST_PROXY=0`.

- [ ] **Step 1: Пересобрать lock** — `bash tools/lock_deps.sh`; Expected: `requirements.lock обновлён`, в файле есть `fastapi`, `SQLAlchemy`, `psycopg`, `alembic`.
- [ ] **Step 2: Собрать образ** — `docker build -t aidigest-backend:dev .`; Expected: успешно; `docker run --rm aidigest-backend:dev pg_dump --version` → `17.x` или выше.
- [ ] **Step 3: Тесты в образе против dev-БД** — `docker run --rm --network host -e AIDIGEST_TEST_DATABASE_URL=postgresql+psycopg://aidigest:aidigest@localhost:5433/aidigest_test aidigest-backend:dev python -m pytest -q -p no:cacheprovider` (на Windows вместо `--network host` — `host.docker.internal:5433`); Expected: всё зелёное, `pg`-тесты не пропущены.
- [ ] **Step 4: Проверка compose** — `docker compose -f docker-compose.yml -f docker-compose.build.yml config` с временным `.env` из `.env.example` (`POSTGRES_PASSWORD=test`); Expected: без ошибок; без `POSTGRES_PASSWORD` — ошибка с текстом «задайте POSTGRES_PASSWORD».
- [ ] **Step 5: Commit** — `build: образ бэкенда и compose для сервера из образов GHCR`

---

### Task 9: Каркас фронтенда: API-клиент, вход, оформление

**Files:**
- Create: `frontend/package.json`, `frontend/package-lock.json`, `frontend/tsconfig.json`, `frontend/vite.config.ts`, `frontend/index.html`, `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/api.ts`, `frontend/src/types.ts`, `frontend/src/safeUrl.ts`, `frontend/src/auth.tsx`, `frontend/src/pages/Login.tsx`, `frontend/src/pages/NotFound.tsx`, `frontend/src/components/Layout.tsx`, `frontend/src/styles.css`, `frontend/src/test/setup.ts`
- Test: `frontend/src/safeUrl.test.ts`, `frontend/src/api.test.ts`, `frontend/src/pages/Login.test.tsx`

**Interfaces:**
- Consumes: эндпоинты Task 7 (`/api/me`, `/api/login`, `/api/logout`, `/api/meta`).
- Produces:
  - Скрипты `package.json`: `dev` (Vite, прокси `/api` и `/healthz` → `http://localhost:8000`), `build` (`tsc -b && vite build`), `typecheck` (`tsc -b --noEmit`), `test` (`vitest run`).
  - Зависимости: `react@18`, `react-dom@18`, `react-router-dom@6`; dev: `vite`, `@vitejs/plugin-react`, `typescript`, `vitest`, `jsdom`, `@testing-library/react`, `@testing-library/user-event`, `@testing-library/jest-dom`.
  - `api.ts`: `class ApiError extends Error { status: number }`; `apiGet<T>(path: string): Promise<T>`, `apiPost<T>(path: string, body?: unknown): Promise<T | null>` (`credentials: "same-origin"`, JSON; 401 → событие `aidigest:unauthorized` на `window` + `ApiError`; текст ошибки — `detail` из ответа).
  - `types.ts`: типы ответов Task 7 (`Meta`, `CaseRow`, `CaseDetail`, `RunCurrent`, `RunRow`, `Credits`, `QueriesResp`, `SourcesResp`).
  - `safeUrl(url: string | null | undefined): string` — `http(s)` или `"#"`.
  - `auth.tsx`: `AuthProvider`, `useAuth(): { authenticated: boolean; loginRequired: boolean; login(u, p): Promise<void>; logout(): Promise<void> }`; `RequireAuth` — без входа ведёт на `/login?next=<путь>`; `next` — только относительный путь, начинающийся с `/` и не с `//`.
  - `Layout` — шапка с навигацией: «Кейсы», «Запуск», «Запросы», «Источники», «Справка», «Выйти» (как `base.html`).
  - `styles.css` — перенос `src/aidigest_web/static/style.css` с правкой селекторов под новую разметку; классы `ok/warn/bad/muted` сохраняются.

- [ ] **Step 1: Создать проект** — `npm create vite@latest frontend -- --template react-ts` (проверить, что версии в `package.json` зафиксированы в `package-lock.json`), добавить зависимости из Interfaces, `vitest` с `environment: "jsdom"`.
- [ ] **Step 2: Падающие тесты**

```ts
// safeUrl.test.ts
expect(safeUrl("javascript:alert(1)")).toBe("#");
expect(safeUrl("https://ai.gov.ru/x")).toBe("https://ai.gov.ru/x");
expect(safeUrl(null)).toBe("#");
// api.test.ts — fetch замокан
it("401 бросает ApiError и шлёт aidigest:unauthorized", ...)
it("ошибка несёт detail из ответа", ...)        // 409 {"detail":"Сбор уже идёт…"} → err.message
// Login.test.tsx
it("неверный пароль показывает текст ошибки сервера", ...)
it("после входа уходит на next, но не на внешний адрес", ...)   // next=//evil.test → "/"
```

- [ ] **Step 3: FAIL** — `cd frontend; npm test` → тесты падают.
- [ ] **Step 4: Реализовать** по Interfaces.
- [ ] **Step 5: PASS** — `npm test`, `npm run typecheck`, `npm run build` — без ошибок.
- [ ] **Step 6: Commit** — `feat(frontend): каркас SPA, вход и оформление`

---

### Task 10: Страницы «Кейсы» и «Кейс», выгрузка

**Files:**
- Create: `frontend/src/pages/Cases.tsx`, `frontend/src/pages/CaseDetail.tsx`, `frontend/src/components/Flags.tsx`
- Test: `frontend/src/pages/Cases.test.tsx`, `frontend/src/pages/CaseDetail.test.tsx`

**Interfaces:**
- Consumes: `GET /api/meta`, `GET /api/cases`, `GET /api/cases/{id}`, `/api/export.xlsx`; `apiGet`, `safeUrl`, `Meta`, `CaseRow`, `CaseDetail`.
- Produces: маршруты `/` и `/case/:id`. Разметка, колонки, тексты и пустые состояния — как в `src/aidigest_web/templates/cases.html` и `case.html`. Фильтры живут в query string (`q, level, status, metrics, doubtful, reliability`; `metrics` по умолчанию `1`), так что ссылка на отфильтрованный список воспроизводима. «Выгрузить в Excel» — обычная ссылка на `/api/export.xlsx`.

- [ ] **Step 1: Падающие тесты**

```tsx
it("фильтры из адреса уходят в запрос", ...)   // /?level=мир&doubtful=1 → fetch("/api/cases?...level=%D0%BC%D0%B8%D1%80...&doubtful=1")
it("пустая база — понятный текст, а не пустая таблица", ...)   // total 0 → текст из cases.html
it("непроверенная главная цифра помечена", ...)  // headline_unverified → пометка как в шаблоне
it("ссылки источников и показателей проходят через safeUrl", ...)  // source_url "javascript:..." → href="#"
it("флаги показывают пояснение из meta.flag_help", ...)
it("неизвестный кейс — страница «Кейс не найден»", ...)
```

- [ ] **Step 2: FAIL** — `npm test`.
- [ ] **Step 3: Реализовать.**
- [ ] **Step 4: PASS** — `npm test && npm run typecheck`.
- [ ] **Step 5: Commit** — `feat(frontend): список кейсов с фильтрами, карточка кейса, выгрузка`

---

### Task 11: Страницы «Запуск», «Запросы», «Источники», «Справка»

**Files:**
- Create: `frontend/src/pages/Run.tsx`, `frontend/src/pages/Queries.tsx`, `frontend/src/pages/Sources.tsx`, `frontend/src/pages/Help.tsx`
- Test: `frontend/src/pages/Run.test.tsx`, `frontend/src/pages/Sources.test.tsx`

**Interfaces:**
- Consumes: `/api/credits`, `/api/runs/current`, `POST /api/runs`, `/api/runs`, `/api/runs/{id}/log`, `/api/queries`, `/api/sources`.
- Produces: маршруты `/run`, `/queries`, `/sources`, `/help`. Тексты и пояснения — из `run.html`, `queries.html`, `sources.html`, `help.html` (смысл без изменений; упоминания «heartbeat», «3 часов» и «сборщик не взял заявку» убрать — их больше нет). На `/run`, пока идёт сбор, `/api/runs/current` опрашивается каждые 5 с (как `static/app.js`); после окончания история перечитывается. Кнопка «Запустить сбор» блокируется, пока идёт сбор или остаток кредитов 0; ответ 409 показывается текстом `detail`. Источник учёта кредитов подписан («по данным Tavily» / «по нашему учёту»). Ссылка «полный лог» — `/api/runs/{id}/log`. В истории у запусков с непустыми `params` — пометка «отладочный» с параметрами.

- [ ] **Step 1: Падающие тесты**

```tsx
it("идёт сбор — минуты и хвост лога, кнопка заблокирована, опрос каждые 5 с", ...)   // fake timers
it("409 при запуске показывает текст сервера", ...)
it("остаток кредитов 0 — кнопка заблокирована", ...)
it("история: прерванный запуск показывает причину, отладочный — пометку с параметрами", ...)
it("источники: фильтр уровня и достоверности уходит в запрос", ...)
```

- [ ] **Step 2: FAIL** — `npm test`.
- [ ] **Step 3: Реализовать.**
- [ ] **Step 4: PASS** — `npm test && npm run typecheck && npm run build`.
- [ ] **Step 5: Commit** — `feat(frontend): страницы запуска, запросов, источников и справки`

---

### Task 12: Образ фронтенда (nginx)

**Files:**
- Create: `frontend/Dockerfile`, `frontend/nginx.conf`, `frontend/.dockerignore`

**Interfaces:**
- Produces: многоэтапный образ: `node:22-alpine` (`npm ci`, `npm run build`) → `nginx:1.27-alpine` с `dist/` в `/usr/share/nginx/html`. `nginx.conf`:
  - `location = /healthz { return 200 "ok"; }`
  - `location /api/ { proxy_pass http://backend:8000; proxy_set_header Host $http_host; proxy_set_header X-Real-IP $remote_addr; proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for; proxy_set_header X-Forwarded-Proto $scheme; proxy_read_timeout 120s; client_max_body_size 1m; }`
  - `location /assets/ { expires 30d; }`, `location / { try_files $uri /index.html; add_header Cache-Control "no-cache"; }`
  - `server_tokens off;`

- [ ] **Step 1: Собрать** — `docker build -t aidigest-frontend:dev frontend`; Expected: успешно.
- [ ] **Step 2: Поднять стек локально** — локальный `.env` (из `.env.example`: `AIDIGEST_DATA_HOST=./data/stack`, `AIDIGEST_SECRETS=.`, `AIDIGEST_HTTP_PORT=8080`, `POSTGRES_PASSWORD=<случайное>`; файл `.env` в `.gitignore`), затем `docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build`. Expected: `docker compose ps` — `db` и `backend` `healthy`, `frontend` `running`; `curl http://localhost:8080/healthz` → `ok`.
- [ ] **Step 3: Проверить в браузере** (`preview_start` с `url: http://localhost:8080`): вход логином/паролем из `web.env`, обновление страницы на `/case/<id>` и `/run` не даёт 404, все пункты меню открываются, в консоли браузера нет ошибок. **Кнопку «Запустить сбор» не нажимать** (Task 15).
- [ ] **Step 4: Перезапуск** — `docker compose restart backend`, затем сайт снова работает без повторного входа (тот же `WEB_SECRET_KEY`).
- [ ] **Step 5: Commit** — `build: образ фронтенда на nginx`

---

### Task 13: CI: тесты и публикация образов в GHCR

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: workflow на `push` (все ветки) и `pull_request`:
  - `backend`: `ubuntu-latest`, service `postgres:17` (`POSTGRES_USER/PASSWORD=aidigest`, `POSTGRES_DB=aidigest_test`, healthcheck), `actions/setup-python` 3.13, `pip install -r requirements.lock -e . --no-deps`, `AIDIGEST_TEST_DATABASE_URL=postgresql+psycopg://aidigest:aidigest@localhost:5432/aidigest_test`, `python -m pytest -q`.
  - `frontend`: `actions/setup-node` 22 с кешем npm, `npm ci`, `npm run typecheck`, `npm test`, `npm run build` (в `frontend/`).
  - `images`: `needs: [backend, frontend]`; `permissions: contents: read, packages: write`; `docker/setup-buildx-action`, `docker/login-action` (`ghcr.io`, `${{ github.actor }}`, `${{ secrets.GITHUB_TOKEN }}`) — только при `github.ref == 'refs/heads/master'`; `docker/metadata-action` → теги `latest` (только master) и `sha-<7 символов>`; `docker/build-push-action` для `.` → `ghcr.io/larch1k/aidigest-backend` и `./frontend` → `ghcr.io/larch1k/aidigest-frontend`; `push: ${{ github.ref == 'refs/heads/master' }}`; кеш `type=gha`.
  - Никаких секретов, кроме `GITHUB_TOKEN`; тесты не получают `*.env`.

- [ ] **Step 1: Проверить синтаксис** — `docker run --rm -v "${PWD}:/repo" -w /repo rhysd/actionlint:latest` → без ошибок.
- [ ] **Step 2: Commit и push ветки** — `git commit -m "ci: тесты и публикация образов в GHCR"`, `git push -u origin feature/three-tier-architecture`.
- [ ] **Step 3: Проверить прогон** — `gh run watch` по последнему запуску ветки: `backend`, `frontend`, `images` зелёные; в `images` образы собраны, но не опубликованы (ветка не master).

---

### Task 14: Документация и запуск для разработки

**Files:**
- Modify: `docs/deploy.md` (переписать), `README.md`, `CLAUDE.md`, `.claude/launch.json`, `docs/pipeline-process.md`

**Interfaces:**
- Produces:
  - `docs/deploy.md`: первая установка с нуля на Ubuntu/Debian (Docker, папки `/srv/aidigest/{data,secrets}`, права UID 1000, `docker-compose.yml` и `.env` — скачать из репозитория `curl -O https://raw.githubusercontent.com/LARCH1K/aiDigest/master/docker-compose.yml` и `.env.example`, секреты `web.env` с `WEB_USERNAME/WEB_PASSWORD/WEB_SECRET_KEY`, `tavily.env`, `litellm.env`; `docker login ghcr.io` — если пакеты приватные, токен только с `read:packages`); выкладка `docker compose pull && docker compose up -d`; откат через `AIDIGEST_VERSION=sha-xxxxxxx`; «если сайт не работает» (`docker compose ps`, `docker compose logs backend`); резервные копии (`data/backend/backups/*.dump`, восстановление `pg_restore`); копия базы себе (`docker compose exec db pg_dump …` → `scp`), обратно не заливать; HTTPS через Caddy перед `frontend` с `AIDIGEST_TRUST_PROXY=1` и нужным `X-Forwarded-For`; предупреждение: перезапуск во время сбора прерывает его, запуск помечается «прервано».
  - `README.md`, `CLAUDE.md`: раздел про пайплайн, веб и сервер — под новую архитектуру (команды разработки: `docker compose -f docker-compose.dev.yml up -d`, `DATABASE_URL`, `python -m aidigest_api`, отладочный сбор `curl -X POST localhost:8000/api/runs -H "Content-Type: application/json" -d '{"budget":5,"levels":["Свердловская область"]}'`, `python -m aidigest eval`, `cd frontend; npm run dev`, тесты бэкенда с `AIDIGEST_TEST_DATABASE_URL`, тесты фронтенда); база — Postgres, а не `data/cases.json`; убрать `AIDIGEST_RUN_MODE`, `aidigest_web.worker`, `deploy.sh`.
  - `.claude/launch.json`: конфигурации `aidigest-api` (`.venv/Scripts/python.exe -m aidigest_api --port 8000`) и `aidigest-frontend` (`npm --prefix frontend run dev`, порт 5173).
  - `docs/pipeline-process.md`: шаги 0, 7, 8 — Postgres вместо `cases.json`/`credits.json`, сохранение подтверждений по одному.

- [ ] **Step 1: Написать документы.**
- [ ] **Step 2: Пройти `docs/deploy.md` по шагам на локальном стеке** (раздел выкладки и отката — с локальным `.env`): команды выполняются без правок.
- [ ] **Step 3: Commit** — `docs: выкладка и разработка в новой архитектуре`

---

### Task 15: Сбор с нуля и проверка качества

**Files:**
- Create: `tools/compare_bases.py`

**Interfaces:**
- Produces: `python tools/compare_bases.py <старый cases.json>` — читает старый файл напрямую (`json` + `Case.model_validate`) и новую базу (`open_storage().cases.load()`); печатает для обеих: число кейсов; доли кейсов с показателями, со статусом «подтверждено», с противоречием; долю показателей с `quote_verified`; распределение по уровням; число кейсов с флагом `цифра_не_найдена_в_тексте`.

Кредиты: перед шагом 2 записать расход Tavily за месяц (отметка «до»); суммарно на Task 15 и всю предыдущую отладку — не больше 250.

- [ ] **Step 1: Эталон** — `.venv/Scripts/python -m aidigest eval --offline` на старой версии (до изменений — `git stash`/чекаут `master` в отдельной папке) и на новой; Expected: результат совпадает (eval не зависит от хранилища).
- [ ] **Step 2: Первый сбор через сайт локального стека** — на `/run` «Запустить сбор» (база пуста → бюджет `first_run_budget: 100`, см. Task 5). Наблюдать ход на странице. Expected: запуск завершён `ok`, в истории есть отчёт.
- [ ] **Step 3: Проверка обрыва** — запустить отладочный сбор с бюджетом 5 (на локальном стеке вход по паролю, поэтому — из консоли браузера на открытом сайте: `fetch("/api/runs", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({budget: 5})})`), через минуту `docker compose restart backend`; Expected: сбор убит вместе с контейнером, после старта бэкенда в истории — «прервано» с `REASON_INTERRUPTED`, кнопка запуска доступна.
- [ ] **Step 4: Сравнение** — `docker compose exec backend python tools/compare_bases.py /data/old_cases.json` (старый `data/cases.json` скопировать в `data/stack/backend/old_cases.json`). Оценить самому: доли «с показателями», «подтверждено», «цитата проверена» не ниже прежних больше чем на 10 процентных пунктов (с учётом разного бюджета: старая база собрана за несколько запусков); распределение по уровням без пустого уровня. При существенном падении — разобраться (`superpowers:systematic-debugging`) и исправить до Task 16. Записать итог и расход кредитов в сообщение коммита.
- [ ] **Step 5: Commit** — `chore: сравнение старой и новой базы, проверка качества сбора`

---

### Task 16: Удаление старой архитектуры и слияние

**Files:**
- Delete: `src/aidigest_web/` целиком, `tests/web/`, `test_litellm.py`
- Modify: `src/aidigest/store.py` (убрать JSON `CaseStore`, `replace_with_retry` перенести в `cache.py`), `src/aidigest/usage.py` (убрать `JsonCreditsRepo`), `src/aidigest/housekeeping.py`, `tests/test_store.py`, `tests/test_housekeeping.py`, `pyproject.toml` (убрать extra `web`, `package-data` для `aidigest_web`), `requirements.lock`, `.gitignore` (убрать `data/cases.json`, `data/credits.json`, `data/web/`, `data/run.cli.lock`; добавить `data/stack/`, `frontend/node_modules/`, `frontend/dist/`)
- Delete (локальные данные, не в git): `data/cases.json`, `data/credits.json`, `data/web/`, `data/run.cli.lock` — `data/cache/` и `data/out/` не трогать

- [ ] **Step 1: Удалить код и зависимости**, пересобрать `requirements.lock` (`bash tools/lock_deps.sh`).
- [ ] **Step 2: Проверка** — `rg -n "aidigest_web|CaseStore\b|credits.json|cases.json|run_lock|AIDIGEST_RUN_MODE" src tests docs/deploy.md README.md CLAUDE.md` → ничего, кроме исторических документов в `docs/superpowers/`; `.venv/Scripts/python -m pytest -q` и `cd frontend; npm test` — зелёные; локальный стек пересобран и открывается.
- [ ] **Step 3: Удалить старые локальные данные** (список выше).
- [ ] **Step 4: Commit и push** — `chore: удалить Flask-сайт, файловое хранилище и test_litellm.py`; CI ветки зелёный.
- [ ] **Step 5: Слияние** — через `superpowers:finishing-a-development-branch`: PR ветки в `master`; после слияния CI на `master` публикует оба образа; проверить, что `ghcr.io/larch1k/aidigest-backend:latest` и `aidigest-frontend:latest` есть в Packages репозитория (`gh api /users/LARCH1K/packages?package_type=container`) и `docker compose pull` с чистым `.env` их скачивает.
