# Трёхзвенная архитектура aiDigest — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перевести aiDigest на три приложения — SPA на React+TS (nginx), бэкенд FastAPI с фоновым сбором, PostgreSQL — с образами в GHCR и выкладкой `docker compose pull && up -d`.

**Architecture:** Пайплайн `src/aidigest/` остаётся, но хранит кейсы в Postgres (в тестах пайплайна — хранилище в памяти). Сервисный слой (`aidigest/services/`) содержит всю логику продукта; FastAPI (`aidigest_api`) — тонкие обработчики над ним. Сбор запускает только бэкенд — подпроцессом `python -m aidigest run …` с выводом в файл лога; записью запуска владеет бэкенд, «один сбор» держит частичный уникальный индекс в Postgres. Кредиты Tavily — только по данным `GET /usage`.

**Tech Stack:** Python 3.13, FastAPI, uvicorn, SQLAlchemy 2 (Core), psycopg 3, Alembic, itsdangerous; React 18 + TypeScript + Vite, react-router-dom, Vitest + Testing Library; nginx:alpine; postgres:17; GitHub Actions + GHCR.

**Spec:** `docs/superpowers/specs/2026-11-15-three-tier-architecture-design.md`

## Global Constraints

- Вся работа — в ветке `feature/three-tier-architecture`; в `master` — целиком после проверки (Task 15–16).
- Образы: `ghcr.io/larch1k/aidigest-backend`, `ghcr.io/larch1k/aidigest-frontend`; теги `latest` и короткий SHA; публикация только с `master`, через `GITHUB_TOKEN`. Образ БД — официальный `postgres:17`, в GHCR не публикуется.
- Бэкенд — **один контейнер**, uvicorn в один процесс; при выкладке никаких проверок «идёт ли сбор».
- **Сбор запускает только бэкенд** (`RunService.start()` — кнопка или `POST /api/runs`). `python -m aidigest run` — команда для подпроцесса; в документации для людей её нет. `aidigest export` удаляется; `aidigest eval` остаётся.
- **Кредиты — только по данным Tavily** (`aidigest.usage.fetch_tavily_usage`). Своего учёта кредитов нет. `/usage` недоступен → «расход неизвестен», сбор разрешён с обычным бюджетом запуска.
- **Резервных копий в коде нет** — только команды в `docs/deploy.md`.
- **Один `docker-compose.yml`** для сервера и локальной проверки (`image:` + `build:` у `backend` и `frontend`).
- **Старый сайт не поддерживается**: удаляется в Task 1; тексты и разметку страниц брать из `master` (`git show master:src/aidigest_web/templates/<файл>`).
- Вход — одна пара `WEB_USERNAME` + `WEB_PASSWORD` (+ `WEB_SECRET_KEY`) из `web.env`. Cookie `Secure` только при `AIDIGEST_SECURE_COOKIE=1`. IP клиента — `X-Real-IP` от nginx; учёта цепочки прокси нет.
- `*.env` никогда не читать, не выводить, не коммитить; в образ и CI не попадают.
- Кредиты Tavily на всю работу по плану — **не больше 250**; перед каждым реальным сбором сверить расход (`fetch_tavily_usage`) с отметкой на старте работы и записать в журнал задачи.
- Тесты не ходят в сеть. Тесты с маркером `pg` ходят в локальный Postgres (`AIDIGEST_TEST_DATABASE_URL`); без переменной пропускаются, в CI переменная задана всегда.
- Любая цифра в кейсе — со ссылкой на источник; логику извлечения/подтверждения/дедупликации не менять (кроме сохранения подтверждений по одному). Промпты `extract.py`, `confirm.py`, `dedup.py` не трогать — это сбросит кеш LLM.
- Кеш `data/cache/` и старый `data/cases.json` не удалять до Task 16.
- Комментарии в коде и тексты интерфейса — на русском; формулировки пояснений (флаги, достоверность, поля запросов/источников, справка) переносятся из старых шаблонов без изменения смысла.
- Ссылки из данных в интерфейсе — только `http(s)`.
- Новые тяжёлые зависимости сверх Tech Stack — не добавлять без обсуждения; UI-фреймворки (MUI, Ant и т.п.) не использовать.

## Review Focus

1. **Вход по `http://<IP>` без HTTPS** — cookie сессии не `Secure`, пока не задан `AIDIGEST_SECURE_COOKIE=1`, иначе вход молча не работает. Тест — Task 7.
2. **Подпроцесс сбора упал, убит или не запустился** — запись не висит «идёт», кнопка снова доступна, причина понятная. Тест — Task 5.
3. **Свежая установка: пустая база, нет ключа Tavily или `/usage` не отвечает** — все страницы и эндпоинты отвечают пустыми состояниями, кредиты — «неизвестно», без 500. Тест — Task 5, Task 7, Task 11.
4. **Повторный старт контейнера на уже мигрированной БД** — миграции идемпотентны, приложение поднимается. Тест — Task 2.
5. **Мусор в отладочных параметрах `POST /api/runs`** (`budget: -1`, неизвестный уровень, `days: 0`) — 422, запись запуска не создаётся. Тест — Task 7.

---

## Карта файлов

```
docker-compose.yml            # db, backend, frontend: image (GHCR) + build
docker-compose.dev.yml        # разработка: только db на 127.0.0.1:5433
docker/dev-init.sql           # создаёт БД aidigest_test
Dockerfile                    # образ бэкенда
alembic.ini
src/aidigest/db/              # engine.py (database_url, make_engine, migrate), schema.py, migrations/
src/aidigest/store.py         # Store (Protocol), StoreData, MemoryStore, PgCaseStore
src/aidigest/usage.py         # TavilyUsage, fetch_tavily_usage (без MonthlyUsage)
src/aidigest/cli.py           # run (для подпроцесса) и eval
src/aidigest/services/cases.py    # фильтры, headline, ярлыки, CaseService
src/aidigest/services/catalog.py  # запросы и источники, CatalogService
src/aidigest/services/runs.py     # RunStore, RunParams, RunService, разбор лога
src/aidigest_api/             # create_app, __main__, auth.py, routes.py, schemas.py
tests/db/conftest.py          # фикстуры pg_engine, pg (маркер pg)
tests/services/, tests/api/
frontend/                     # Vite + React + TS, Dockerfile, nginx.conf
.github/workflows/ci.yml
tools/compare_bases.py        # сравнение старой и новой базы (Task 15)
```

---

### Task 1: Логика представления — в сервисы, старый сайт — удалить

**Files:**
- Create: `src/aidigest/services/__init__.py`, `src/aidigest/services/cases.py`, `src/aidigest/services/catalog.py`
- Create: `tests/services/test_cases.py` (из `tests/web/test_views.py`), `tests/services/test_catalog.py` (логика из `tests/web/test_config_pages.py`), `tests/services/test_run_log.py` (тесты `parse_report` из `tests/web/test_runs.py` и `_reason` из тестов runner)
- Delete: `src/aidigest_web/`, `tests/web/`, `src/aidigest/runlock.py`, `tests/test_runlock.py`, `deploy.sh`, `.claude/launch.json` (конфиг `aidigest-web`; новый — в Task 14)
- Modify: `src/aidigest/cli.py` (убрать `run_lock`/`RunLocked`/`EXIT_LOCKED`), `tests/test_pipeline.py` (убрать `test_cli_run_refuses_when_locked`), `pyproject.toml` (убрать extra `web` и `package-data` для `aidigest_web`), `.gitignore` (убрать `data/run.cli.lock`)

**Interfaces:**
- Produces:
  - `services.cases` — всё из `aidigest_web/views.py` с теми же именами: `filter_cases`, `headline`, `short_line`, `sort_key`, `best_reliability`, `reliability_rank`, `FLAG_HELP`, `STATUS_LABEL`, `STATUS_CLASS`, `RELIABILITY_ORDER`, `RELIABILITY_LABEL`, `RELIABILITY_CLASS`, `NO_RATED`, `DOUBTFUL`.
  - `services.catalog` — из `aidigest_web/config_pages.py`: `ANY_RF_LEVEL`, `ANY_RF_LABEL`, `level_label`, `group_queries`, `filter_sources`, `CONFIG_ERRORS`.
  - `services.runs` (заготовка, расширяется в Task 5): `REPORT_PREFIXES`, `STATE_LABEL` (без `busy`), `parse_report(log_text: str) -> dict[str, str]`, `last_reason(log_text: str) -> str | None` (последняя строка `Причина: …` без префикса; перенос `runner._reason`).

- [ ] **Step 1: Перенести тесты** в `tests/services/` с импортами из `aidigest.services.*`.
- [ ] **Step 2: FAIL** — `.venv/Scripts/python -m pytest tests/services -q` → `ModuleNotFoundError`.
- [ ] **Step 3: Перенести код** в `services/` без изменения логики; удалить файлы из списка Delete; убрать блокировку из `cli.py`.
- [ ] **Step 4: PASS** — `.venv/Scripts/python -m pytest -q` зелёный; `rg -n "aidigest_web|run_lock|runlock" src tests pyproject.toml` → пусто.
- [ ] **Step 5: Commit** — `refactor: логика представления в aidigest.services, старый Flask-сайт удалён`

---

### Task 2: Postgres для разработки, схема и миграции

**Files:**
- Create: `docker-compose.dev.yml`, `docker/dev-init.sql`, `alembic.ini`, `src/aidigest/db/__init__.py`, `src/aidigest/db/engine.py`, `src/aidigest/db/schema.py`, `src/aidigest/db/migrations/env.py`, `src/aidigest/db/migrations/script.py.mako`, `src/aidigest/db/migrations/versions/0001_initial.py`
- Modify: `pyproject.toml` (зависимости + маркер `pg` + extra `api`)
- Test: `tests/db/conftest.py`, `tests/db/test_schema.py`

**Interfaces:**
- Produces:
  - `database_url() -> str` — `DATABASE_URL` из окружения, иначе `postgresql+psycopg://aidigest:aidigest@localhost:5433/aidigest`.
  - `make_engine(url: str | None = None) -> sqlalchemy.Engine` (`pool_pre_ping=True`).
  - `migrate(engine: Engine) -> None` — `alembic upgrade head` программно; путь к миграциям — относительно пакета.
  - Таблицы (`schema.metadata`):
    - `cases(id text PK, level text NOT NULL, first_seen date NOT NULL, updated date NOT NULL, data jsonb NOT NULL)`
    - `processed_urls(url text PK, added timestamptz NOT NULL DEFAULT now())`
    - `runs(id text PK, state text NOT NULL, started timestamptz NOT NULL, finished timestamptz, exit_code int, reason text, report jsonb NOT NULL DEFAULT '{}', params jsonb NOT NULL DEFAULT '{}')`
    - частичный уникальный индекс `runs_one_running ON runs ((true)) WHERE state = 'running'`.
  - Фикстуры: `pg_engine` (session) — `AIDIGEST_TEST_DATABASE_URL`, иначе `pytest.skip("нет AIDIGEST_TEST_DATABASE_URL")`; пересоздаёт схему `public`, вызывает `migrate`. `pg` (function) — `TRUNCATE cases, processed_urls, runs`, отдаёт engine.

- [ ] **Step 1: Зависимости** — в `pyproject.toml`: `sqlalchemy>=2`, `psycopg[binary]>=3.2`, `alembic`; extra `api = ["fastapi", "uvicorn", "itsdangerous", "httpx"]`; `markers = ["pg: тест ходит в Postgres (AIDIGEST_TEST_DATABASE_URL)"]`. `.venv/Scripts/python -m pip install -e ".[dev,api]"`.
- [ ] **Step 2: Dev-компоуз** — `docker-compose.dev.yml`: `db` на `postgres:17`, `POSTGRES_USER/PASSWORD/DB = aidigest`, порт `127.0.0.1:5433:5432`, именованный том, `docker/dev-init.sql` (`CREATE DATABASE aidigest_test;`) в `/docker-entrypoint-initdb.d/`. `docker compose -f docker-compose.dev.yml up -d` → `db` running.
- [ ] **Step 3: Падающие тесты**

```python
# tests/db/test_schema.py
pytestmark = pytest.mark.pg

def test_tables_exist(pg):
    assert {"cases", "processed_urls", "runs"} <= set(inspect(pg).get_table_names())

def test_migrate_is_idempotent(pg):          # Review Focus 4
    migrate(pg); migrate(pg)

def test_only_one_running_run(pg):
    ins = text("INSERT INTO runs (id, state, started) VALUES (:id, 'running', now())")
    with pg.begin() as c: c.execute(ins, {"id": "a"})
    with pytest.raises(IntegrityError):
        with pg.begin() as c: c.execute(ins, {"id": "b"})
```

- [ ] **Step 4: FAIL** — `$env:AIDIGEST_TEST_DATABASE_URL="postgresql+psycopg://aidigest:aidigest@localhost:5433/aidigest_test"; .venv/Scripts/python -m pytest tests/db -q` → `ModuleNotFoundError: aidigest.db`.
- [ ] **Step 5: Реализовать** engine, schema, миграцию `0001_initial`, фикстуры.
- [ ] **Step 6: PASS** — `3 passed`; без переменной — `3 skipped`; весь набор зелёный.
- [ ] **Step 7: Commit** — `feat(db): Postgres для разработки, схема и миграции`

---

### Task 3: Кейсы в Postgres, подтверждения по одному

**Files:**
- Modify: `src/aidigest/store.py`, `src/aidigest/pipeline.py:19,66,139,147-158`, `src/aidigest/cli.py`, `src/aidigest/housekeeping.py` (удалить `backup_cases`, `BACKUPS_KEEP`)
- Modify: `tests/test_pipeline.py`, `tests/test_store.py`, `tests/test_housekeeping.py`, `tests/conftest.py`
- Test: `tests/db/test_pg_store.py`, `tests/test_pipeline.py`

**Interfaces:**
- Produces (`aidigest.store`):
  - `class Store(Protocol): def load(self) -> StoreData; def save(self, data: StoreData) -> None`
  - `class MemoryStore` — хранит глубокую копию (`model_copy(deep=True)`), чтобы тесты ловили «забыли save».
  - `class PgCaseStore(engine)`: `load()` — все кейсы (`Case.model_validate(data)`) и URL; `save(data)` — **одна транзакция**: upsert всех кейсов (`ON CONFLICT (id) DO UPDATE SET level, first_seen, updated, data`) и `INSERT processed_urls … ON CONFLICT DO NOTHING`; кейсы не удаляет. `updated_at() -> datetime | None` — `max(processed_urls.added)`.
  - JSON `CaseStore` удаляется; `replace_with_retry` переезжает в `cache.py`.
  - `Deps.store: Store`.
  - В `cli.py`: `_case_store() -> Store` (по умолчанию `PgCaseStore(make_engine())` с `migrate`); фикстура `case_store` в `tests/conftest.py` подменяет её на `MemoryStore()`.
  - Команда `export` удаляется вместе с `cmd_export`.

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
    assert PgCaseStore(pg).load() == StoreData() and PgCaseStore(pg).updated_at() is None

def test_save_is_atomic(pg, make_case):
    bad = make_case(id="c2"); object.__setattr__(bad, "level", None)   # сломает INSERT
    with pytest.raises(Exception):
        PgCaseStore(pg).save(StoreData([make_case(id="c1"), bad], {"https://x.ru/1"}))
    assert PgCaseStore(pg).load() == StoreData()
```

```python
# tests/test_pipeline.py
def test_confirmations_saved_one_by_one(registry, case_reply):
    """Подтверждение второго кейса падает (KeyboardInterrupt из FakeSearch) — результат первого уже в базе:
    store.load() у первого кейса confirmation_attempts == 1."""
```

- [ ] **Step 2: FAIL** — `pytest tests/db/test_pg_store.py tests/test_pipeline.py -q`.
- [ ] **Step 3: Реализовать**; в `run_cycle` после каждого кейса очереди подтверждения (успех и ветки `except`, кроме `BudgetExceeded`) — `deps.store.save(data)`; финальный `save` оставить. Тесты пайплайна и `cmd_run` перевести с `CaseStore(tmp_path …)` на `MemoryStore`/фикстуру `case_store`; удалить `test_cli_export_offline` и тесты `backup_cases`.
- [ ] **Step 4: PASS** — весь набор зелёный.
- [ ] **Step 5: Commit** — `feat(store): кейсы в Postgres, подтверждения сохраняются по одному`

---

### Task 4: Кредиты только по данным Tavily

**Files:**
- Modify: `src/aidigest/usage.py` (удалить `MonthlyUsage`), `src/aidigest/cli.py`, `src/aidigest/config.py` (удалить `monthly_limit`), `config/settings.yaml` (удалить `monthly_limit`; `monthly_warn_share` оставить)
- Modify: `tests/test_usage.py`, `tests/test_pipeline.py`, `.gitignore` (убрать `data/credits.json`)
- Test: `tests/test_cli_run.py`

**Interfaces:**
- Consumes: `fetch_tavily_usage(token) -> TavilyUsage | None`.
- Produces — поведение `aidigest run [--first-run] [--budget N] [--levels …] [--days N] [--offline]`:
  - `requested` = `--budget`, иначе `first_run_budget` при `--first-run` **или пустой базе**, иначе `run_budget`.
  - `actual = fetch_tavily_usage(token)`; `actual` есть → печать `Кредиты по данным Tavily: {used:g} из {limit:g}.`; `requested > 0` и `actual.remaining <= 0` → печать `Причина: Месячный лимит кредитов Tavily исчерпан — новый сбор возможен после пополнения.`, выход 2; иначе бюджет `min(requested, actual.remaining)` (с сообщением об урезании, как сейчас). `actual is None` → печать `Расход кредитов Tavily неизвестен (сервис не ответил) — бюджет запуска {requested:g}.` и бюджет `requested`.
  - Предупреждение о расходе: `actual.used > actual.limit * monthly_warn_share` → `Внимание: …` (как сейчас).
  - Строка отчёта `Кредитов Tavily за месяц` убирается. Коды выхода: 0 — успех, 1 — ошибка, 2 — лимит.

- [ ] **Step 1: Падающие тесты** (`tests/test_cli_run.py`, фикстура `case_store`, `fetch_tavily_usage` подменён)

```python
def test_run_refuses_when_tavily_says_exhausted(case_store, usage_says, capsys):
    usage_says(TavilyUsage(used=1000, limit=1000))
    assert main(["run", "--offline", "--budget", "5"]) == 2
    assert "Причина: Месячный лимит" in capsys.readouterr().out

def test_run_caps_budget_by_tavily_remaining(case_store, usage_says, capsys): ...   # remaining 3, budget 30 → урезан до 3
def test_run_with_unknown_usage_uses_requested_budget(case_store, usage_says, capsys):
    usage_says(None)
    assert main(["run", "--offline", "--budget", "5"]) == 0
    assert "Расход кредитов Tavily неизвестен" in capsys.readouterr().out

def test_run_uses_first_run_budget_on_empty_base(case_store, usage_says, capsys): ...  # в выводе бюджет 100
```

Тесты `MonthlyUsage` в `tests/test_usage.py` удалить; тесты `fetch_tavily_usage` оставить. Старые `test_cli_run_*` про `credits.json` удалить или переписать на поведение выше.

- [ ] **Step 2: FAIL** — `pytest tests/test_cli_run.py -q`.
- [ ] **Step 3: Реализовать.**
- [ ] **Step 4: PASS** — весь набор; `rg -n "MonthlyUsage|credits.json|monthly_limit" src tests config` → пусто.
- [ ] **Step 5: Commit** — `feat(usage): кредиты только по данным Tavily, без своего учёта`

---

### Task 5: Запуски: хранилище и RunService

**Files:**
- Modify: `src/aidigest/services/runs.py`
- Test: `tests/services/test_runs.py` (маркер `pg`)

**Interfaces:**
- Consumes: `parse_report`, `last_reason` (Task 1), `fetch_tavily_usage`, `Settings`, `make_engine`.
- Produces (`aidigest.services.runs`):
  - Константы: `STATE_BY_CODE = {0: "ok", 2: "limit"}` (прочие коды — `"error"`), `REASON_INTERRUPTED = "Сбор прерван перезапуском сервера. Кейсы, которые он успел сохранить, уже в базе."`, `REASON_CRASHED = "Сборщик завершился аварийно — сообщите команде разработки."`, `REASON_SPAWN_FAILED = "Не удалось запустить сбор — сообщите команде разработки."`, `RUNS_KEEP = 100`.
  - `class AlreadyRunning(Exception)`, `class MonthExhausted(Exception)`.
  - `@dataclass RunRecord(run_id: str, state: str, started: datetime, finished: datetime | None, exit_code: int | None, reason: str | None, report: dict[str, str], params: dict)`; свойства `label`, `minutes`.
  - `class RunStore(engine)`:
    - `create(run_id: str, started: datetime, params: dict) -> None` — state `running`; `IntegrityError` по `runs_one_running` → `AlreadyRunning`.
    - `finish(run_id, state, exit_code, reason, report: dict, finished: datetime) -> bool` — только если запись `running`.
    - `interrupt_running(now: datetime) -> int`.
    - `current() -> RunRecord | None`, `get(run_id) -> RunRecord | None`, `history(limit: int = 10) -> list[RunRecord]` (по `started` убыв.), `prune(keep: int = RUNS_KEEP) -> list[str]` (удалённые id).
  - `@dataclass RunParams(budget: float | None = None, levels: list[Level] | None = None, days: int | None = None, offline: bool = False)`; `to_argv() -> list[str]` (`--budget N`, `--levels a,b`, `--days N`, `--offline`); `as_dict() -> dict` (только заданные поля, уровни — строками).
  - `class RunService(store: RunStore, data_dir: Path, project_root: Path, settings: Settings, tavily_token: str | None, popen=subprocess.Popen, now=datetime.now, fetch_usage=fetch_tavily_usage)`:
    - `credits() -> dict` — `{"known": bool, "used": float | None, "limit": float | None, "remaining": float | None, "plan": str, "run_budget": float}`; ответ Tavily кешируется на 60 с.
    - `start(params: RunParams | None = None) -> str` — `known` и `remaining <= 0` и не `offline` → `MonthExhausted`; `run_id = now().strftime("%Y%m%d-%H%M%S")`; `store.create(...)`; лог `<data_dir>/runs/<run_id>.log` (папка создаётся); `popen([sys.executable, "-m", "aidigest", "run", *params.to_argv()], cwd=project_root, stdout=log, stderr=STDOUT, env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "AIDIGEST_DATA_DIR": str(data_dir)})`. `popen` бросил → `finish(run_id, "error", None, REASON_SPAWN_FAILED, {}, now)` и исключение дальше. Поток-наблюдатель: `code = proc.wait()`, текст лога → `finish(run_id, STATE_BY_CODE.get(code, "error"), code, last_reason(text) or (REASON_CRASHED if code not in (0, 2) else None), parse_report(text), now)`; затем `prune()` и удаление файлов логов удалённых запусков.
    - `current() -> tuple[RunRecord, list[str]] | None` — запись и последние 30 строк лога.
    - `history(limit=10) -> list[RunRecord]`, `log(run_id) -> str | None` (текст файла; нет записи или файла → `None`).
    - `on_startup() -> int` — `store.interrupt_running(now)`.
    - `join_watchers(timeout: float = 5) -> None` — для тестов.

- [ ] **Step 1: Падающие тесты** (`pytestmark = pytest.mark.pg`; фейковый `popen` пишет заданный текст в переданный `stdout` и возвращает объект с `wait() -> code`)

```python
def test_start_spawns_and_finishes_ok(svc_child):
    svc = svc_child(code=0, output="Кейсов новых: 3\n")
    rid = svc.start(); svc.join_watchers()
    r = svc.store.get(rid)
    assert r.state == "ok" and r.report == {"Кейсов новых": "3"} and "Кейсов новых" in svc.log(rid)

def test_params_go_to_argv_and_record(svc_child, popen_calls):
    svc = svc_child(code=0)
    rid = svc.start(RunParams(budget=5, levels=[Level.SVERDLOVSK], offline=True))
    assert popen_calls[0][3:] == ["run", "--budget", "5", "--levels", "Свердловская область", "--offline"]
    assert svc.store.get(rid).params == {"budget": 5, "levels": ["Свердловская область"], "offline": True}

def test_start_twice_raises(svc_child):
    svc = svc_child(code=0, block=True); svc.start()
    with pytest.raises(AlreadyRunning): svc.start()

def test_limit_exit_code(svc_child):
    svc = svc_child(code=2, output="Причина: Месячный лимит кредитов Tavily исчерпан\n")
    rid = svc.start(); svc.join_watchers()
    assert svc.store.get(rid).state == "limit"

def test_crash_without_reason_marks_error(svc_child):               # Review Focus 2
    svc = svc_child(code=-9, output="Traceback ...\n")
    rid = svc.start(); svc.join_watchers()
    r = svc.store.get(rid); assert r.state == "error" and r.reason == REASON_CRASHED
    svc.start()                                                      # кнопка снова доступна

def test_popen_failure_closes_record(svc_popen_raises):
    with pytest.raises(OSError): svc_popen_raises.start()
    assert svc_popen_raises.store.current() is None
    assert svc_popen_raises.store.history(1)[0].reason == REASON_SPAWN_FAILED

def test_month_exhausted_refuses(svc_usage):
    svc = svc_usage(TavilyUsage(used=1000, limit=1000))
    with pytest.raises(MonthExhausted): svc.start()
    assert svc.store.history() == []

def test_unknown_usage_allows_start(svc_usage):                       # Review Focus 3
    svc = svc_usage(None)
    assert svc.credits()["known"] is False and svc.start()

def test_on_startup_interrupts_left_running(svc_child):
    svc = svc_child(code=0); svc.store.create("old", NOW, {})
    assert svc.on_startup() == 1 and svc.store.get("old").reason == REASON_INTERRUPTED

def test_prune_removes_old_logs(svc_child): ...   # RUNS_KEEP=2 через monkeypatch; после трёх запусков — 2 записи и 2 файла
```

- [ ] **Step 2: FAIL** — `pytest tests/services/test_runs.py -q`.
- [ ] **Step 3: Реализовать.**
- [ ] **Step 4: PASS** — весь набор зелёный.
- [ ] **Step 5: Commit** — `feat(runs): запуски в Postgres, сбор подпроцессом с логом в файл`

---

### Task 6: Сервисы кейсов и справочников

**Files:**
- Modify: `src/aidigest/services/cases.py`, `src/aidigest/services/catalog.py`
- Test: `tests/services/test_cases.py`, `tests/services/test_catalog.py`

**Interfaces:**
- Produces:
  - `@dataclass CaseFilter(q: str = "", level: str = "", status: str = "", with_metrics: bool = True, hide_doubtful: bool = False, reliability: str = "")`
  - `class CaseService(store: Store)`: `list(f: CaseFilter) -> tuple[list[Case], int]` (отфильтрованные, всего); `get(case_id: str) -> Case | None`; `export_xlsx() -> bytes` (через `export_xlsx` во временной папке, без остатков файлов); `updated_at() -> datetime | None` (если у store есть `updated_at`, иначе `None`).
  - `class CatalogService(config_dir: Path)`: `queries() -> tuple[list[tuple[Level, list[QuerySpec]]], int, int, str | None]` (группы, всего, `freshness_days`, ошибка); `sources(level: str = "", reliability: str = "") -> tuple[list[SourceInfo], int, str | None]`. Ошибки чтения YAML (`CONFIG_ERRORS`) — текст `Не удалось прочитать <файл>: <тип ошибки>.`, не исключение.

- [ ] **Step 1: Падающие тесты**

```python
def test_case_service_filters_and_counts(make_case):
    st = MemoryStore(); st.save(StoreData([make_case(id="a"), make_case(id="b", metrics=[])], set()))
    shown, total = CaseService(st).list(CaseFilter())
    assert [c.id for c in shown] == ["a"] and total == 2

def test_get_unknown_is_none(): assert CaseService(MemoryStore()).get("x") is None
def test_export_returns_xlsx_bytes_and_leaves_no_files(make_case, tmp_path, monkeypatch): ...   # bytes[:2] == b"PK", tempdir пуст
def test_catalog_broken_yaml_returns_error(tmp_path):
    (tmp_path / "queries.yaml").write_text("queries: [", encoding="utf-8")
    groups, total, _, error = CatalogService(tmp_path).queries()
    assert groups == [] and total == 0 and error.startswith("Не удалось прочитать queries.yaml")
def test_catalog_real_configs():                                  # config/ репозитория
    assert CatalogService(ROOT / "config").queries()[1] > 0 and CatalogService(ROOT / "config").sources()[1] > 0
```

- [ ] **Step 2: FAIL** — `pytest tests/services -q`.
- [ ] **Step 3: Реализовать.**
- [ ] **Step 4: PASS** — весь набор.
- [ ] **Step 5: Commit** — `feat(services): сервисы кейсов и справочников`

---

### Task 7: HTTP API на FastAPI

**Files:**
- Create: `src/aidigest_api/__init__.py`, `__main__.py`, `auth.py`, `routes.py`, `schemas.py`
- Modify: `src/aidigest/creds.py` (`WEB_KEYS = ("WEB_USERNAME", "WEB_PASSWORD", "WEB_SECRET_KEY")`)
- Test: `tests/api/conftest.py`, `tests/api/test_auth.py`, `tests/api/test_cases.py`, `tests/api/test_runs.py`, `tests/api/test_catalog.py` (маркер `pg`)

**Interfaces:**
- Consumes: `CaseService`, `CatalogService`, `RunService`, `RunStore`, `RunParams`, `PgCaseStore`, `migrate`.
- Produces:
  - `create_app(engine: Engine, *, username: str | None, password: str | None, secret_key: str | None, secure_cookie: bool = False, config_dir: Path | None = None, data_dir: Path | None = None, run_service: RunService | None = None) -> FastAPI`. Lifespan: `migrate(engine)`, `run_service.on_startup()`.
  - Сессия: `SessionMiddleware(secret_key, session_cookie="aidigest_session", same_site="strict", https_only=secure_cookie, max_age=14 * 24 * 3600)`.
  - Без `password` вход отключён (локальная разработка), но запрос с `Host` не из `localhost`/`127.0.0.1`/`[::1]` → 400.
  - POST: `Sec-Fetch-Site` не `same-origin`/`none` → 403; `Origin` есть и его хост ≠ `Host` → 403.
  - `client_ip(request) -> str` — `X-Real-IP`, иначе `request.client.host`.
  - `LoginLimiter` — перенос из `git show master:src/aidigest_web/auth.py` (10 неудач за 600 с; `BLOCKED_TEXT = "Слишком много неудачных попыток. Подождите 10 минут."`).
  - Эндпоинты (все, кроме `/healthz`, `/api/login`, `/api/me`, требуют сессию → 401 `{"detail": "нужен вход"}`):

    | Метод и путь | Ответ |
    |---|---|
    | `GET /healthz` | `ok` (text/plain), без БД |
    | `POST /api/login` `{username, password}` | 204 + cookie; 401 `{"detail": "Неверный логин или пароль"}`; 429 `{"detail": BLOCKED_TEXT}`; `hmac.compare_digest` для обоих полей |
    | `POST /api/logout` | 204 |
    | `GET /api/me` | `{"authenticated": bool, "login_required": bool}` |
    | `GET /api/meta` | `{"levels": [...], "statuses": [{"value","label","class"}], "reliability": [{"value","label"}], "flag_help": {flag: [что, что делать]}}` |
    | `GET /api/cases?q&level&status&metrics=1&doubtful=0&reliability` | `{"total", "updated": iso\|null, "cases": [CaseRow]}`; `CaseRow`: `id, title, level, country, region, organization, industry, stage, first_seen, status, status_label, status_class, headline, headline_unverified, reliability, reliability_label, reliability_class, flags` |
    | `GET /api/cases/{id}` | `Case.model_dump(mode="json")` + `status_label`, `status_class`, `reliability_label`; 404 `{"detail": "Кейс не найден"}` |
    | `GET /api/export.xlsx` | файл `aidigest_cases_<ГГГГ-ММ-ДД>.xlsx` |
    | `GET /api/credits` | `RunService.credits()` |
    | `GET /api/runs/current` | `{"running": false}` или `{"running": true, "run_id", "started", "minutes", "tail": [...]}` |
    | `POST /api/runs` (тело необязательно: `{"budget"?: число > 0, "levels"?: [уровень из Level], "days"?: целое ≥ 1, "offline"?: bool}`) | 202 `{"run_id"}`; 422 при неверных полях; 409 `{"detail": "Сбор уже идёт — дождитесь, пока он закончится."}`; 409 `{"detail": "Лимит кредитов Tavily исчерпан — новый сбор возможен после пополнения лимита."}` |
    | `GET /api/runs?limit=10` | `[{"run_id","state","label","started","finished","minutes","exit_code","reason","report","params"}]` |
    | `GET /api/runs/{id}/log` | text/plain; 404 |
    | `GET /api/queries` | `{"groups": [{"level", "queries": [...]}], "total", "freshness_days", "error"}` |
    | `GET /api/sources?level&reliability` | `{"sources": [...], "total", "error", "level_options", "reliability_options"}` |
  - `__main__`: `python -m aidigest_api [--host 127.0.0.1] [--port 8000]`; ключи `web.env` через `load_creds(ROOT / "web.env", WEB_KEYS)`; не-локальный хост без `WEB_USERNAME`/`WEB_PASSWORD` или без `WEB_SECRET_KEY` → выход 2 с понятным текстом (по образцу `git show master:src/aidigest_web/__main__.py`); `AIDIGEST_SECURE_COOKIE=1` → `secure_cookie`; `AIDIGEST_DATA_DIR` (по умолчанию `ROOT / "data"`); `uvicorn.run(app, host=…, port=…, workers=1)`. `RunService` получает `tavily_token` из `tavily.env`/окружения.

- [ ] **Step 1: Падающие тесты** (TestClient, `pg`, фейковый `popen`)

```python
def test_api_requires_login(client):
    assert client.get("/api/cases").status_code == 401

def test_login_cookie_not_secure_by_default(client):                 # Review Focus 1
    r = client.post("/api/login", json={"username": "u", "password": "p"})
    cookie = r.headers["set-cookie"].lower()
    assert r.status_code == 204 and "aidigest_session=" in cookie and "secure" not in cookie and "samesite=strict" in cookie

def test_login_cookie_secure_when_enabled(secure_client):
    assert "secure" in secure_client.post("/api/login", json={"username": "u", "password": "p"}).headers["set-cookie"].lower()

def test_wrong_password_then_block(client):
    for _ in range(10): client.post("/api/login", json={"username": "u", "password": "x"})
    assert client.post("/api/login", json={"username": "u", "password": "p"}).status_code == 429

def test_limiter_uses_real_ip_header(client):
    for _ in range(10):
        client.post("/api/login", json={"username": "u", "password": "x"}, headers={"X-Real-IP": "1.1.1.1"})
    assert client.post("/api/login", json={"username": "u", "password": "p"}, headers={"X-Real-IP": "2.2.2.2"}).status_code == 204

def test_cross_site_post_rejected(authed):
    assert authed.post("/api/runs", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert authed.post("/api/runs", headers={"Origin": "http://evil.test"}).status_code == 403

def test_empty_base_everything_answers(authed):                       # Review Focus 3
    assert authed.get("/api/cases").json() == {"total": 0, "updated": None, "cases": []}
    assert authed.get("/api/runs/current").json() == {"running": False}
    assert authed.get("/api/runs").json() == []
    assert authed.get("/api/credits").json()["known"] is False
    assert authed.get("/api/export.xlsx").status_code == 200

def test_case_list_filters_and_detail(authed_with_cases): ...         # metrics=0 показывает кейс без цифр; 404 на неизвестный id
def test_start_run_and_conflict(authed_blocking_child): ...           # 202, затем 409 «Сбор уже идёт…»
def test_start_run_passes_debug_params(authed, popen_calls): ...      # {"budget": 5, "levels": ["Свердловская область"], "offline": true} → argv

@pytest.mark.parametrize("body", [{"budget": -1}, {"levels": ["марс"]}, {"days": 0}])
def test_start_run_rejects_bad_params(authed, body):                  # Review Focus 5
    assert authed.post("/api/runs", json=body).status_code == 422
    assert authed.get("/api/runs").json() == []

def test_queries_and_sources(authed): ...                             # реальные config/*.yaml: total > 0, error is None
def test_foreign_host_rejected_without_password(open_client):
    assert open_client.get("/api/cases", headers={"Host": "evil.test"}).status_code == 400
def test_startup_interrupts_left_running(pg, make_client): ...        # запись running до старта → interrupted после старта
```

- [ ] **Step 2: FAIL** — `pytest tests/api -q`.
- [ ] **Step 3: Реализовать** по Interfaces.
- [ ] **Step 4: PASS** — весь набор; вручную: `$env:DATABASE_URL="postgresql+psycopg://aidigest:aidigest@localhost:5433/aidigest"; .venv/Scripts/python -m aidigest_api --port 8001`; `curl http://localhost:8001/healthz` → `ok`; `curl http://localhost:8001/api/cases` → JSON.
- [ ] **Step 5: Commit** — `feat(api): HTTP API на FastAPI поверх сервисного слоя`

---

### Task 8: Образ бэкенда и docker-compose.yml

**Files:**
- Replace: `Dockerfile`, `docker-compose.yml`
- Modify: `.dockerignore`, `tools/lock_deps.sh` (extra `[api,dev]`), `requirements.lock`, `.env.example`

**Interfaces:**
- Produces:
  - Образ бэкенда: `python:3.13-slim`, `tzdata`, `TZ=Asia/Yekaterinburg`, `PYTHONPATH=/app/src`, `PYTHONUNBUFFERED=1`, `PYTHONIOENCODING=utf-8`, `AIDIGEST_DATA_DIR=/data`, `EXPOSE 8000`, `CMD ["python", "-m", "aidigest_api", "--host", "0.0.0.0", "--port", "8000"]`. В образе `config/`, `eval/`, `alembic.ini`, миграции.
  - `docker-compose.yml`:
    - `db`: `postgres:17`, `POSTGRES_USER=aidigest`, `POSTGRES_DB=aidigest`, `POSTGRES_PASSWORD=${POSTGRES_PASSWORD:?задайте POSTGRES_PASSWORD в .env}`, том `${AIDIGEST_DATA_HOST:-/srv/aidigest/data}/postgres:/var/lib/postgresql/data`, healthcheck `pg_isready -U aidigest`, порт не публикуется.
    - `backend`: `image: ghcr.io/larch1k/aidigest-backend:${AIDIGEST_VERSION:-latest}`, `build: .`, `user: "${AIDIGEST_UID:-1000}:${AIDIGEST_GID:-1000}"`, `DATABASE_URL=postgresql+psycopg://aidigest:${POSTGRES_PASSWORD}@db:5432/aidigest`, `AIDIGEST_SECURE_COOKIE=${AIDIGEST_SECURE_COOKIE:-0}`, том `${AIDIGEST_DATA_HOST:-/srv/aidigest/data}/backend:/data`, `env_file` — `web.env`, `tavily.env`, `litellm.env` из `${AIDIGEST_SECRETS:-/srv/aidigest/secrets}` (`required: false`), `depends_on: db: condition: service_healthy`, healthcheck `http://localhost:8000/healthz`, `init: true`, порт не публикуется.
    - `frontend`: `image: ghcr.io/larch1k/aidigest-frontend:${AIDIGEST_VERSION:-latest}`, `build: ./frontend`, `ports: "${AIDIGEST_HTTP_PORT:-80}:80"`, `depends_on: backend`.
    - Всем: `restart: unless-stopped`, логи json-file `10m × 3`.
  - `.env.example`: `AIDIGEST_VERSION=latest`, `AIDIGEST_DATA_HOST`, `AIDIGEST_SECRETS`, `AIDIGEST_HTTP_PORT`, `AIDIGEST_UID/GID`, `POSTGRES_PASSWORD=` (комментарий: только буквы и цифры, например `openssl rand -hex 24`), `AIDIGEST_SECURE_COOKIE=0`.

- [ ] **Step 1: Пересобрать lock** — `bash tools/lock_deps.sh`; Expected: в файле есть `fastapi`, `SQLAlchemy`, `psycopg`, `alembic`, нет `Flask`, `waitress`.
- [ ] **Step 2: Собрать образ** — `docker build -t aidigest-backend:dev .` → успешно.
- [ ] **Step 3: Тесты в образе против dev-БД** — `docker run --rm -e AIDIGEST_TEST_DATABASE_URL=postgresql+psycopg://aidigest:aidigest@host.docker.internal:5433/aidigest_test aidigest-backend:dev python -m pytest -q -p no:cacheprovider` → всё зелёное, `pg`-тесты не пропущены.
- [ ] **Step 4: Проверка compose** — `docker compose config` с временным `.env` (`POSTGRES_PASSWORD=test`) → без ошибок; без `POSTGRES_PASSWORD` → ошибка «задайте POSTGRES_PASSWORD».
- [ ] **Step 5: Commit** — `build: образ бэкенда и docker-compose.yml для сервера и локальной проверки`

---

### Task 9: Каркас фронтенда: API-клиент, вход, оформление

**Files:**
- Create: `frontend/package.json`, `frontend/package-lock.json`, `frontend/tsconfig.json`, `frontend/vite.config.ts`, `frontend/index.html`, `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/api.ts`, `frontend/src/types.ts`, `frontend/src/safeUrl.ts`, `frontend/src/auth.tsx`, `frontend/src/pages/Login.tsx`, `frontend/src/pages/NotFound.tsx`, `frontend/src/components/Layout.tsx`, `frontend/src/styles.css`, `frontend/src/test/setup.ts`
- Modify: `.gitignore` (`frontend/node_modules/`, `frontend/dist/`)
- Test: `frontend/src/safeUrl.test.ts`, `frontend/src/api.test.ts`, `frontend/src/pages/Login.test.tsx`

**Interfaces:**
- Consumes: эндпоинты Task 7 (`/api/me`, `/api/login`, `/api/logout`, `/api/meta`).
- Produces:
  - Скрипты: `dev` (Vite, прокси `/api` и `/healthz` → `http://localhost:8000`), `build` (`tsc -b && vite build`), `typecheck` (`tsc -b --noEmit`), `test` (`vitest run`).
  - Зависимости: `react@18`, `react-dom@18`, `react-router-dom@6`; dev: `vite`, `@vitejs/plugin-react`, `typescript`, `vitest`, `jsdom`, `@testing-library/react`, `@testing-library/user-event`, `@testing-library/jest-dom`.
  - `api.ts`: `class ApiError extends Error { status: number }`; `apiGet<T>(path: string): Promise<T>`, `apiPost<T>(path: string, body?: unknown): Promise<T | null>` (`credentials: "same-origin"`, JSON; 401 → событие `aidigest:unauthorized` на `window` + `ApiError`; текст ошибки — `detail` из ответа).
  - `types.ts`: типы ответов Task 7 (`Meta`, `CaseRow`, `CaseDetail`, `RunCurrent`, `RunRow`, `Credits`, `QueriesResp`, `SourcesResp`).
  - `safeUrl(url: string | null | undefined): string` — `http(s)` или `"#"`.
  - `auth.tsx`: `AuthProvider`, `useAuth(): { authenticated: boolean; loginRequired: boolean; login(u, p): Promise<void>; logout(): Promise<void> }`; `RequireAuth` — без входа на `/login?next=<путь>`; `next` — только путь, начинающийся с `/` и не с `//`.
  - `Layout` — шапка: «Кейсы», «Запуск», «Запросы», «Источники», «Справка», «Выйти» (как `master:src/aidigest_web/templates/base.html`).
  - `styles.css` — перенос `master:src/aidigest_web/static/style.css` с правкой селекторов; классы `ok/warn/bad/muted` сохраняются.

- [ ] **Step 1: Создать проект** — `npm create vite@latest frontend -- --template react-ts`, зависимости из Interfaces, `vitest` с `environment: "jsdom"`.
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

- [ ] **Step 3: FAIL** — `cd frontend; npm test`.
- [ ] **Step 4: Реализовать.**
- [ ] **Step 5: PASS** — `npm test`, `npm run typecheck`, `npm run build`.
- [ ] **Step 6: Commit** — `feat(frontend): каркас SPA, вход и оформление`

---

### Task 10: Страницы «Кейсы» и «Кейс», выгрузка

**Files:**
- Create: `frontend/src/pages/Cases.tsx`, `frontend/src/pages/CaseDetail.tsx`, `frontend/src/components/Flags.tsx`
- Test: `frontend/src/pages/Cases.test.tsx`, `frontend/src/pages/CaseDetail.test.tsx`

**Interfaces:**
- Consumes: `GET /api/meta`, `GET /api/cases`, `GET /api/cases/{id}`, `/api/export.xlsx`; `apiGet`, `safeUrl`, `Meta`, `CaseRow`, `CaseDetail`.
- Produces: маршруты `/` и `/case/:id`. Разметка, колонки, тексты и пустые состояния — как в `master:src/aidigest_web/templates/cases.html` и `case.html`. Фильтры — в query string (`q, level, status, metrics, doubtful, reliability`; `metrics` по умолчанию `1`). «Выгрузить в Excel» — ссылка на `/api/export.xlsx`.

- [ ] **Step 1: Падающие тесты**

```tsx
it("фильтры из адреса уходят в запрос", ...)          // /?level=мир&doubtful=1 → fetch("/api/cases?...level=%D0%BC%D0%B8%D1%80...&doubtful=1")
it("пустая база — понятный текст, а не пустая таблица", ...)
it("непроверенная главная цифра помечена", ...)
it("ссылки источников и показателей проходят через safeUrl", ...)   // "javascript:..." → href="#"
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
- Produces: маршруты `/run`, `/queries`, `/sources`, `/help`. Тексты — из `master:src/aidigest_web/templates/{run,queries,sources,help}.html` (смысл без изменений; убрать упоминания heartbeat, «3 часов», «сборщик не взял заявку», «по нашему учёту»). На `/run`, пока идёт сбор, `/api/runs/current` опрашивается каждые 5 с; после окончания история перечитывается. Кнопка «Запустить сбор» заблокирована, пока идёт сбор или `credits.known && credits.remaining <= 0`; 409 показывается текстом `detail`. Кредиты: `known` → «потрачено X из Y (по данным Tavily)», иначе «расход неизвестен — Tavily не ответил». Ссылка «полный лог» — `/api/runs/{id}/log`. В истории у запусков с непустыми `params` — пометка «отладочный» с параметрами.

- [ ] **Step 1: Падающие тесты**

```tsx
it("идёт сбор — минуты и хвост лога, кнопка заблокирована, опрос каждые 5 с", ...)   // fake timers
it("409 при запуске показывает текст сервера", ...)
it("остаток кредитов 0 — кнопка заблокирована", ...)
it("расход неизвестен — понятный текст, кнопка доступна", ...)        // Review Focus 3
it("история: прерванный показывает причину, отладочный — пометку с параметрами", ...)
it("источники: фильтр уровня и достоверности уходит в запрос", ...)
```

- [ ] **Step 2: FAIL** — `npm test`.
- [ ] **Step 3: Реализовать.**
- [ ] **Step 4: PASS** — `npm test && npm run typecheck && npm run build`.
- [ ] **Step 5: Commit** — `feat(frontend): страницы запуска, запросов, источников и справки`

---

### Task 12: Образ фронтенда (nginx) и локальный стек

**Files:**
- Create: `frontend/Dockerfile`, `frontend/nginx.conf`, `frontend/.dockerignore`
- Modify: `.gitignore` (`data/stack/`)

**Interfaces:**
- Produces: многоэтапный образ: `node:22-alpine` (`npm ci`, `npm run build`) → `nginx:1.27-alpine` с `dist/` в `/usr/share/nginx/html`. `nginx.conf`:
  - `location = /healthz { return 200 "ok"; }`
  - `location /api/ { proxy_pass http://backend:8000; proxy_set_header Host $http_host; proxy_set_header X-Real-IP $remote_addr; proxy_read_timeout 120s; client_max_body_size 1m; }`
  - `location /assets/ { expires 30d; }`, `location / { try_files $uri /index.html; add_header Cache-Control "no-cache"; }`
  - `server_tokens off;`

- [ ] **Step 1: Собрать** — `docker build -t aidigest-frontend:dev frontend` → успешно.
- [ ] **Step 2: Поднять стек** — локальный `.env` из `.env.example` (`AIDIGEST_DATA_HOST=./data/stack`, `AIDIGEST_SECRETS=.`, `AIDIGEST_HTTP_PORT=8080`, `POSTGRES_PASSWORD=<случайное>`), `docker compose up -d --build`. Expected: `db` и `backend` `healthy`, `frontend` `running`; `curl http://localhost:8080/healthz` → `ok`.
- [ ] **Step 3: Проверить в браузере** (`preview_start` с `url: http://localhost:8080`): вход логином/паролем из `web.env`, обновление на `/case/<id>` и `/run` не даёт 404, все пункты меню открываются, в консоли браузера нет ошибок. **Кнопку «Запустить сбор» не нажимать** (Task 15).
- [ ] **Step 4: Перезапуск** — `docker compose restart backend` → сайт работает без повторного входа.
- [ ] **Step 5: Commit** — `build: образ фронтенда на nginx`

---

### Task 13: CI: тесты и публикация образов в GHCR

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: workflow на `push` (все ветки) и `pull_request`:
  - `backend`: `ubuntu-latest`, service `postgres:17` (`POSTGRES_USER/PASSWORD=aidigest`, `POSTGRES_DB=aidigest_test`, healthcheck), `actions/setup-python` 3.13, `pip install -r requirements.lock -e . --no-deps`, `AIDIGEST_TEST_DATABASE_URL=postgresql+psycopg://aidigest:aidigest@localhost:5432/aidigest_test`, `python -m pytest -q`.
  - `frontend`: `actions/setup-node` 22 с кешем npm, `npm ci`, `npm run typecheck`, `npm test`, `npm run build` (в `frontend/`).
  - `images`: `needs: [backend, frontend]`; `permissions: contents: read, packages: write`; `docker/setup-buildx-action`; `docker/login-action` (`ghcr.io`, `${{ github.actor }}`, `${{ secrets.GITHUB_TOKEN }}`) только при `github.ref == 'refs/heads/master'`; `docker/metadata-action` → `latest` (только master) и `sha-<7 символов>`; `docker/build-push-action` для `.` → `ghcr.io/larch1k/aidigest-backend` и `./frontend` → `ghcr.io/larch1k/aidigest-frontend`; `push: ${{ github.ref == 'refs/heads/master' }}`; кеш `type=gha`.
  - Никаких секретов, кроме `GITHUB_TOKEN`.

- [ ] **Step 1: Синтаксис** — `docker run --rm -v "${PWD}:/repo" -w /repo rhysd/actionlint:latest` → без ошибок.
- [ ] **Step 2: Commit и push ветки** — `ci: тесты и публикация образов в GHCR`; `git push -u origin feature/three-tier-architecture`.
- [ ] **Step 3: Прогон** — `gh run watch`: `backend`, `frontend`, `images` зелёные; образы собраны, не опубликованы.

---

### Task 14: Документация и запуск для разработки

**Files:**
- Modify: `docs/deploy.md` (переписать), `README.md`, `CLAUDE.md`, `docs/pipeline-process.md`
- Create: `.claude/launch.json`

**Interfaces:**
- Produces:
  - `docs/deploy.md`: первая установка с нуля на Ubuntu/Debian (Docker, папки `/srv/aidigest/{data,secrets}`, права UID 1000; `curl -O https://raw.githubusercontent.com/LARCH1K/aiDigest/master/docker-compose.yml` и `.env.example` → `.env`; секреты `web.env` с `WEB_USERNAME/WEB_PASSWORD/WEB_SECRET_KEY`, `tavily.env`, `litellm.env`; `docker login ghcr.io` — если пакеты приватные, токен только с `read:packages`); выкладка `docker compose pull && docker compose up -d`; откат `AIDIGEST_VERSION=sha-xxxxxxx`; «если сайт не работает» (`docker compose ps`, `docker compose logs backend`); **резервные копии**: `docker compose exec -T db pg_dump -U aidigest -Fc aidigest > backup_$(date +%F).dump`, восстановление `pg_restore`, пример строки cron (ежедневно, хранить 14 копий); копия базы себе (`scp`), обратно не заливать; HTTPS позже — Caddy перед `frontend`, `AIDIGEST_SECURE_COOKIE=1`, и тогда же доработать определение IP клиента; предупреждение: перезапуск во время сбора прерывает его, запуск помечается «прервано».
  - `README.md`, `CLAUDE.md`: разделы про пайплайн, веб и сервер — под новую архитектуру: `docker compose -f docker-compose.dev.yml up -d`, `DATABASE_URL`, `python -m aidigest_api`, отладочный сбор (вход без пароля локально) `curl -X POST localhost:8000/api/runs -H "Content-Type: application/json" -d '{"budget":5,"levels":["Свердловская область"]}'`, `python -m aidigest eval`, `cd frontend; npm run dev`, тесты бэкенда с `AIDIGEST_TEST_DATABASE_URL`, тесты фронтенда; база — Postgres; кредиты — только по данным Tavily; убрать `AIDIGEST_RUN_MODE`, `aidigest_web`, `deploy.sh`, `credits.json`, `aidigest run`/`export` из команд для людей.
  - `.claude/launch.json`: `aidigest-api` (`.venv/Scripts/python.exe -m aidigest_api --port 8000`) и `aidigest-frontend` (`npm --prefix frontend run dev`, порт 5173).
  - `docs/pipeline-process.md`: шаги 0, 7, 8 — Postgres вместо `cases.json`, кредиты только по Tavily, подтверждения сохраняются по одному, Excel — с сайта.

- [ ] **Step 1: Написать документы.**
- [ ] **Step 2: Пройти `docs/deploy.md` на локальном стеке** (выкладка, откат, копия и восстановление базы) — команды выполняются без правок.
- [ ] **Step 3: Commit** — `docs: выкладка и разработка в новой архитектуре`

---

### Task 15: Сбор с нуля и проверка качества

**Files:**
- Create: `tools/compare_bases.py`

**Interfaces:**
- Produces: `python tools/compare_bases.py <старый cases.json>` — читает старый файл (`json` + `Case.model_validate`) и новую базу (`PgCaseStore(make_engine()).load()`); печатает для обеих: число кейсов; доли кейсов с показателями, «подтверждено», «противоречие»; долю показателей с `quote_verified`; распределение по уровням; число кейсов с флагом `цифра_не_найдена_в_тексте`.

Кредиты: перед шагом 2 записать расход Tavily (отметка «до»); суммарно на всю работу — не больше 250.

- [ ] **Step 1: Эталон** — `.venv/Scripts/python -m aidigest eval --offline` на `master` (отдельная папка через `git worktree add`) и на ветке → результат совпадает.
- [ ] **Step 2: Первый сбор через сайт локального стека** — `/run` → «Запустить сбор» (база пуста → `first_run_budget: 100`). Expected: `ok`, в истории отчёт.
- [ ] **Step 3: Проверка обрыва** — отладочный сбор с бюджетом 5 из консоли браузера на открытом сайте: `fetch("/api/runs", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({budget: 5})})`; через минуту `docker compose restart backend`. Expected: после старта — «прервано» с `REASON_INTERRUPTED`, кнопка доступна.
- [ ] **Step 4: Сравнение** — `data/cases.json` скопировать в `data/stack/backend/old_cases.json`; `docker compose exec backend python tools/compare_bases.py /data/old_cases.json`. Оценить самому: доли «с показателями», «подтверждено», «цитата проверена» не ниже прежних больше чем на 10 процентных пунктов (старая база собрана за несколько запусков); ни один уровень не пуст. Существенное падение — разобраться (`superpowers:systematic-debugging`) и исправить. Итог и расход кредитов — в сообщение коммита.
- [ ] **Step 5: Commit** — `chore: сравнение старой и новой базы, проверка качества сбора`

---

### Task 16: Уборка и слияние

**Files:**
- Delete: `test_litellm.py`
- Modify: `.gitignore` (убрать `data/cases.json`, `data/web/`)
- Delete (локальные данные, не в git): `data/cases.json`, `data/credits.json`, `data/web/`, `data/run.cli.lock`, `data/stack/backend/old_cases.json` — `data/cache/` и `data/out/` не трогать

- [ ] **Step 1: Проверка** — `rg -n "aidigest_web|CaseStore\b|credits.json|cases.json|run_lock|AIDIGEST_RUN_MODE|MonthlyUsage|deploy.sh" src tests docs/deploy.md README.md CLAUDE.md` → пусто; `.venv/Scripts/python -m pytest -q` и `cd frontend; npm test` — зелёные.
- [ ] **Step 2: Удалить** файлы из списков выше.
- [ ] **Step 3: Commit и push** — `chore: удалить test_litellm.py и старые данные`; CI ветки зелёный.
- [ ] **Step 4: Слияние** — через `superpowers:finishing-a-development-branch`: PR ветки в `master`; после слияния CI на `master` публикует оба образа; проверить их в Packages (`gh api /users/LARCH1K/packages?package_type=container`) и что `docker compose pull` с чистым `.env` их скачивает.
