# Развёртывание aiDigest на сервере — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** выкладывать aiDigest на Linux-сервер одной командой `./deploy.sh` так, чтобы сбор по кнопке переживал перевыкладку, не шёл в двух экземплярах, не забивал диск и при неудаче показывал на сайте понятную причину.

**Architecture:** Docker Compose, один образ, два сервиса. **web** — сайт. **worker** — новый `aidigest_web.worker`: он берёт заявки на сбор из папки с данными и выполняет их через существующий `runner`. Признак того, что сбор жив, — heartbeat-файл вместо номера процесса. В `aidigest run` добавляются межпроцессная блокировка и строка `Причина: …`. Ключи читаются из переменных окружения, файлы `*.env` остаются запасным вариантом. Данные лежат в папке хоста вне git.

**Tech Stack:** Python 3.13, Flask, waitress, pytest, Docker Compose, bash. Новых Python-зависимостей нет, кроме `werkzeug.middleware.proxy_fix`: он входит во Flask.

**Spec:** `docs/superpowers/specs/2026-11-08-server-deployment-design.md`

## Global Constraints

- `litellm.env`, `tavily.env`, `web.env` и любые `*.env` не открывать, не печатать, не коммитить. Ключи не должны попадать в образ (`.dockerignore`), git или логи.
- Тесты в сеть не ходят. Кредиты Tavily не тратятся: кнопку «Запустить сбор» не нажимать, `aidigest run` вызывать только с `--offline`.
- Локальная разработка под Windows работает как сейчас: `python -m aidigest_web`, `python -m aidigest run`, `.venv/Scripts/python -m pytest -q`.
- Python ≥ 3.12, базовый образ `python:3.13-slim`. Тяжёлых зависимостей не добавлять.
- Часовой пояс контейнеров — `Asia/Yekaterinburg`.
- Комментарии и тексты для пользователя — на русском.
- Коды выхода `aidigest run`: 0 — успех, 1 — ошибка, 2 — месячный лимит, 3 — уже идёт другой сбор.
- Сроки хранения: кеш Tavily — 14 дней, кеш LLM и HTTP (`fetch`) — 180 дней, запуски в `web/runs` — последние 100, `out/*.xlsx` — последние 30, `backups/` — последние 30.
- Ограничение входа: 10 неудачных попыток за 600 секунд с одного IP.
- Таймаут LLM: 120 секунд, `max_retries=1`.
- Heartbeat обновляется каждые 15 секунд и считается устаревшим через 90 секунд.

## Review Focus

1. **Worker не работает, а кнопку нажали.** Запуск не должен висеть «идёт» три часа: через 90 секунд он помечается прерванным с причиной «Сборщик не взял заявку…». Тест в Task 5.
2. **Офлайн-запуск или `--budget 0`, когда поисковых запросов не было вовсе, — это не «все поиски упали».** Код 0. Тест в Task 4.
3. **Бюджет кончился на первом же запросе (`BudgetExceeded`)** — это не ошибка поиска. Тест в Task 4.
4. **Пустая переменная окружения (`TAVILY_TOKEN=`) не перекрывает значение из файла.** Тест в Task 1.
5. **Исключение внутри сбора освобождает блокировку CLI**, и следующий запуск проходит. Тест в Task 3.

---

### Task 1: Ключи из переменных окружения

**Files:**
- Modify: `src/aidigest/creds.py`
- Modify: `src/aidigest/cli.py` (функция `_creds`)
- Modify: `src/aidigest_web/runs.py` (метод `_tavily`)
- Modify: `src/aidigest_web/__main__.py` (функция `_web_env`, `main`)
- Test: `tests/test_creds.py`, `tests/web/test_auth.py`

**Interfaces:**
- Produces: `load_creds(path: Path, keys: tuple[str, ...]) -> dict[str, str]` в `aidigest.creds`. Значения из файла (если он есть) перекрываются непустыми переменными окружения с теми же именами. Если файла нет, берутся только переменные. Ключи с пустым значением в результат не попадают.
- Наборы ключей (константы в `aidigest.creds`): `LITELLM_KEYS = ("LITELLM_API_KEY", "LITELLM_BASE_URL", "LITELLM_MODEL")`, `TAVILY_KEYS = ("TAVILY_TOKEN",)`, `WEB_KEYS = ("WEB_PASSWORD", "WEB_SECRET_KEY")`.

- [ ] **Step 1: Write the failing tests** в `tests/test_creds.py`:
  - `test_load_creds_env_overrides_file`: в файле `TAVILY_TOKEN=file`, `monkeypatch.setenv("TAVILY_TOKEN", "env")` → `{"TAVILY_TOKEN": "env"}`.
  - `test_load_creds_without_file_uses_env`: файла нет, переменная есть → `{"TAVILY_TOKEN": "env"}`.
  - `test_load_creds_empty_env_does_not_override`: файл `TAVILY_TOKEN=file`, `setenv("TAVILY_TOKEN", "")` → `{"TAVILY_TOKEN": "file"}`.
  - `test_load_creds_nothing_gives_empty`: ни файла, ни переменных → `{}`. Перед проверкой `monkeypatch.delenv(..., raising=False)`.
- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_creds.py -q`. Expected: FAIL (`ImportError: load_creds`).
- [ ] **Step 3: Implement `load_creds`.** `load_env_file` не меняется.
- [ ] **Step 4: Подключить.**
  - `cli._creds(name, offline)` → `load_creds(ROOT / name, keys)` с набором по имени файла. `SystemExit(f"Не найдены ключи {name}: задайте файл в корне проекта или переменные окружения.")` выбрасывается, только если результат пуст и запуск не офлайн.
  - `RunManager._tavily` → `load_creds(self.project_root / "tavily.env", TAVILY_KEYS).get("TAVILY_TOKEN")`.
  - `aidigest_web.__main__._web_env` → `load_creds(PROJECT_ROOT / "web.env", WEB_KEYS)`.
- [ ] **Step 5: Постоянный секретный ключ в сети.** В `aidigest_web.__main__.main` при нелокальном `--host` без `WEB_SECRET_KEY` вернуть 2 с сообщением «Открыть сайт в сеть без постоянного ключа нельзя: задайте WEB_SECRET_KEY (иначе каждая перевыкладка разлогинивает пользователей).». Тесты в `tests/web/test_auth.py`:
  - `test_main_refuses_network_without_secret_key`: пароль задан через `monkeypatch.setenv`, ключа нет → `main(["--host", "0.0.0.0"]) == 2`;
  - существующий `test_main_allows_network_with_password` дополнить `WEB_SECRET_KEY`.

  Чтобы тесты не зависели от настоящего `web.env`, `_web_env` в них подменяется через monkeypatch, как в существующих тестах.
- [ ] **Step 6: Run** `.venv/Scripts/python -m pytest -q`. Expected: все PASS.
- [ ] **Step 7: Commit** `feat: ключи из переменных окружения, постоянный WEB_SECRET_KEY для сети`.

### Task 2: Таймаут LLM

**Files:**
- Modify: `src/aidigest/llm.py` (`LiteLLMClient.__init__`)
- Test: `tests/test_llm.py`

**Interfaces:**
- Produces: константы `LLM_TIMEOUT_SECONDS = 120`, `LLM_MAX_RETRIES = 1` в `aidigest.llm`.

- [ ] **Step 1: Write the failing test** `test_client_uses_timeout_and_single_retry`: `monkeypatch.setattr("openai.OpenAI", fake)`, где `fake` запоминает kwargs. `LiteLLMClient("k", "http://x", "m", DiskCache(tmp_path))` → `kwargs["timeout"] == 120 and kwargs["max_retries"] == 1`.
- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_llm.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** Передать `timeout=LLM_TIMEOUT_SECONDS, max_retries=LLM_MAX_RETRIES` в `openai.OpenAI(...)`.
- [ ] **Step 4: Run** тот же тест. Expected: PASS. Промпты не меняются, кеш LLM не сбрасывается.
- [ ] **Step 5: Commit** `fix: таймаут 120 с и один повтор для LLM`.

### Task 3: Межпроцессная блокировка `aidigest run`

**Files:**
- Create: `src/aidigest/runlock.py`
- Modify: `src/aidigest/cli.py` (`cmd_run`)
- Test: `tests/test_runlock.py`, `tests/test_pipeline.py`

**Interfaces:**
- Produces: `class RunLocked(Exception)`. `run_lock(data_dir: Path)` — контекст-менеджер, который берёт эксклюзивную неблокирующую блокировку файла `<data_dir>/run.cli.lock`: `fcntl.flock(LOCK_EX | LOCK_NB)` в Linux, `msvcrt.locking(LK_NBLCK, 1)` в Windows. Если блокировка занята, бросает `RunLocked`. ОС снимает блокировку, когда процесс умирает, поэтому старый файл ничего не блокирует.
- Produces: `EXIT_LOCKED = 3` в `aidigest.cli`.

- [ ] **Step 1: Write the failing tests** в `tests/test_runlock.py`:
  - `test_second_lock_is_refused`: внутри `with run_lock(tmp_path):` второй `run_lock(tmp_path).__enter__()` бросает `RunLocked`;
  - `test_lock_released_after_exception`: `with pytest.raises(ValueError): with run_lock(tmp_path): raise ValueError` → потом `with run_lock(tmp_path): pass` без ошибки.

  Если на Windows блокировка внутри одного процесса себя не видит, второй захват проверяется отдельным процессом через `subprocess.run([sys.executable, "-c", ...])` с кодом выхода 3.
- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_runlock.py -q`. Expected: FAIL (`ModuleNotFoundError`).
- [ ] **Step 3: Implement `run_lock`.**
- [ ] **Step 4: Подключить в `cmd_run`.** Вся работа после загрузки настроек, включая сверку с Tavily, идёт внутри `with run_lock(_data_dir()):`. При `RunLocked` печатается `Причина: уже идёт другой сбор — дождитесь его окончания.` и возвращается `EXIT_LOCKED`. Тест в `tests/test_pipeline.py`: `test_cli_run_refuses_when_locked` — держим `run_lock(tmp_path)` и вызываем `main(["run", "--offline", "--budget", "0"])`. Ожидаем `3` и строку `Причина:` в `capsys`. Сценарий Windows-внутри-процесса обрабатывается так же, как в Step 1.
- [ ] **Step 5: Run** `.venv/Scripts/python -m pytest -q`. Expected: PASS.
- [ ] **Step 6: Commit** `feat: aidigest run не запускается, пока идёт другой сбор`.

### Task 4: Понятная причина неудачи в `aidigest run`

**Files:**
- Create: `src/aidigest/failure.py`
- Modify: `src/aidigest/pipeline.py` (`RunReport`, `run_cycle`)
- Modify: `src/aidigest/cli.py` (`cmd_run`)
- Test: `tests/test_failure.py`, `tests/test_pipeline.py`

**Interfaces:**
- Produces: `explain(exc: BaseException, service: str | None = None) -> str` в `aidigest.failure`. Правила по порядку:
  1. `OSError` с `errno.ENOSPC` → «На сервере кончилось место на диске.»
  2. Код ответа 401 или 403 (`exc.status_code`, `exc.response.status_code` или классы `openai.AuthenticationError`/`PermissionDeniedError`, у Tavily — `InvalidAPIKeyError`) → `f"{service} не принял ключ — проверьте ключ на сервере."`
  3. Сеть, таймаут или 5xx (`requests.ConnectionError`, `requests.Timeout`, `openai.APIConnectionError`, `openai.APITimeoutError`, `openai.InternalServerError`, код ≥ 500) → `f"{service} недоступен (сеть или сбой сервиса) — попробуйте позже."`
  4. Иначе → `f"{service or 'Сбор'}: неожиданная ошибка ({type(exc).__name__}) — подробности в логе."`

  `service` — `"Tavily"` или `"LiteLLM"`. Если `service is None`, в правилах 2–3 используется «Внешний сервис».
- Produces: новые поля `RunReport`: `searches_ok: int = 0`, `searches_failed: int = 0`, `last_search_error: BaseException | None = None`, `last_llm_error: BaseException | None = None`. В `as_rows()` они не выводятся.
- Produces: `failure_reason(report: RunReport) -> str | None` в `aidigest.failure`:
  - если `searches_ok == 0` и `searches_failed > 0` → `"Ни один поисковый запрос не выполнился. " + explain(last_search_error, "Tavily")`;
  - иначе если `articles_processed == 0` и `articles_failed > 0` → `"Ни одна статья не обработана. " + explain(last_llm_error, "LiteLLM")`;
  - иначе `None`.

- [ ] **Step 1: Write the failing tests** в `tests/test_failure.py`:
  - `test_explain_disk_full`: `OSError(errno.ENOSPC, "x")` → строка содержит «кончилось место»;
  - `test_explain_auth`: объект с `status_code = 401` → «Tavily не принял ключ»;
  - `test_explain_network`: `requests.ConnectionError()` с `service="LiteLLM"` → «LiteLLM недоступен»;
  - `test_failure_reason_all_searches_failed`: `RunReport(searches_failed=3, last_search_error=requests.Timeout())` → начинается с «Ни один поисковый запрос»;
  - `test_failure_reason_no_searches_is_ok`: `RunReport()` → `None` (Review Focus 2);
  - `test_failure_reason_llm`: `RunReport(searches_ok=1, articles_failed=2, last_llm_error=...)` → начинается с «Ни одна статья».
- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_failure.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement `explain` и `failure_reason`.** В `run_cycle` при успешном поиске увеличивать `searches_ok`, в ветке `except Exception` — `searches_failed` и запоминать `last_search_error`, в ветке ошибки статьи — `last_llm_error`. `BudgetExceeded` в счётчики не попадает.
- [ ] **Step 4: Тест пайплайна** `test_budget_exhausted_first_query_is_not_failure` в `tests/test_pipeline.py` (Review Focus 3): `FakeSearch` с бюджетом 0 → `failure_reason(report) is None`. Плюс `test_cycle_counts_failed_searches`: поиск бросает `requests.ConnectionError` → `report.searches_failed == len(queries)`.
- [ ] **Step 5: Подключить в `cmd_run`.**
  - Вызов `run_cycle` обернуть так: при любом исключении `traceback.print_exc()`, печать `Причина: {explain(e)}`, `return 1`. `usage.record` в `finally` остаётся.
  - После успешного `run_cycle` отчёт и Excel печатаются как сейчас. Затем, если `failure_reason(report)` не `None`, печатается `Причина: …` и возвращается 1.

  Тест `test_cli_run_prints_reason_on_crash`: `monkeypatch.setattr("aidigest.pipeline.run_cycle", raising_fn)` с `OSError(errno.ENOSPC, "x")` → код 1, в выводе `Причина: На сервере кончилось место`. Импорт `run_cycle` в `cmd_run` локальный, так что патчится модуль `aidigest.pipeline`.
- [ ] **Step 6: Run** `.venv/Scripts/python -m pytest -q`. Expected: PASS.
- [ ] **Step 7: Commit** `feat: строка «Причина:» при неудачном сборе; все упавшие поиски — ошибка`.

### Task 5: Heartbeat вместо номера процесса и причина на сайте

**Files:**
- Modify: `src/aidigest_web/runner.py`
- Modify: `src/aidigest_web/runs.py`
- Modify: `src/aidigest_web/templates/run.html`
- Test: `tests/web/test_runs.py`, `tests/web/test_security.py`, `tests/web/test_run_page.py`

**Interfaces:**
- Produces в `aidigest_web.runs`:
  - `HEARTBEAT_SECONDS = 15`, `HEARTBEAT_STALE_SECONDS = 90`;
  - путь `<data>/web/runs/<id>.heartbeat`;
  - `RunManager(data_dir, project_root, popen=..., now=datetime.now, clock=time.time, mode="local")`. Параметр `pid_alive` удаляется. `clock` — секунды для сравнения с mtime файлов.
  - `RunInfo.reason: str | None = None`.
  - Итог `<id>.json` получает поле `"reason"` (строка или `null`). Старые итоги без этого поля читаются.
  - `STATE_BY_CODE = {0: "ok", 2: "limit", 3: "busy"}`, `STATE_LABEL["busy"] = "уже шёл другой сбор"`.
- Produces в `aidigest_web.runner`: `main(argv)` как сейчас. Дополнительно, пока ждёт процесс сбора, он в фоновом потоке обновляет heartbeat каждые `HEARTBEAT_SECONDS` (первое обновление — до запуска процесса). После завершения пишет `reason` — последнюю строку лога, начинающуюся с `Причина: `, без префикса. Файл `.pid` больше не пишется.
- Правило жизни в `RunManager._current()`:
  - сбор жив, если heartbeat моложе `HEARTBEAT_STALE_SECONDS`;
  - если heartbeat ещё нет, сбор жив, пока моложе `HEARTBEAT_STALE_SECONDS` сам `run.lock`;
  - иначе пишется итог `interrupted` с причиной:
    - heartbeat не появлялся → «Сборщик не взял заявку — сообщите команде разработки.»;
    - heartbeat устарел → «Сбор оборвался (перезапуск или сбой сервера). Кейсы, которые он успел сохранить, уже в базе.»
  - `MAX_RUN_AGE` остаётся.

- [ ] **Step 1: Обновить тесты под новое правило.** В `tests/web/test_runs.py` `manager()` принимает `clock` вместо `alive`.
  - `test_dead_pid_without_result_is_interrupted` → `test_stale_heartbeat_is_interrupted`: heartbeat с `os.utime` на 100 с старше `clock()` → `current() is None`, `history()[0].state == "interrupted"`, в `reason` есть «оборвался».
  - `test_runner_pid_file_overrides_launcher_pid` удалить.
  - Новые тесты:
    - `test_fresh_heartbeat_keeps_run_alive`;
    - `test_no_heartbeat_young_lock_is_running`;
    - `test_no_heartbeat_old_lock_says_worker_missing` (Review Focus 1: причина содержит «Сборщик не взял заявку»);
    - `test_runner_writes_heartbeat_and_reason`: FakeProc пишет в лог `Причина: Tavily недоступен…` и возвращает 1 → в итоге `state == "error"`, `reason` начинается с «Tavily недоступен», файл `.heartbeat` существует;
    - `test_old_result_without_reason_is_readable`.
  - В `test_runner_binds_itself_before_spawning_and_writes_pid` вместо `.pid` проверять `.heartbeat`.
  - Правки в `tests/web/test_security.py` — по тем же правилам.
- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/web -q`. Expected: новые тесты FAIL.
- [ ] **Step 3: Implement** в `runner.py` и `runs.py`. `default_pid_alive` и чтение `.pid` удалить. Windows Job Object в `runner` оставить.
- [ ] **Step 4: Шаблон `run.html`.**
  - В карточке «Последний запуск» при `last.reason` показать `<p class="error">{{ last.reason }}</p>` над ссылкой на лог.
  - При состоянии `error` без причины показать «Сбор завершился с ошибкой — подробности в логе.»
  - Текст про прерванный сбор («например, выключили компьютер») заменить на `last.reason`, если причина есть.
  - В таблице истории под меткой итога мелким шрифтом выводится `r.reason`.

  Тест в `tests/web/test_run_page.py`: `test_run_page_shows_reason` — итог с `reason` виден на `/run`.
- [ ] **Step 5: Run** `.venv/Scripts/python -m pytest -q`. Expected: PASS.
- [ ] **Step 6: Commit** `feat(web): жив ли сбор — по heartbeat; причина ошибки на странице запуска`.

### Task 6: Режим очереди и worker

**Files:**
- Create: `src/aidigest_web/worker.py`
- Modify: `src/aidigest_web/runs.py` (`_start`)
- Modify: `src/aidigest_web/__init__.py` (`create_app`), `src/aidigest_web/__main__.py`
- Test: `tests/web/test_worker.py`

**Interfaces:**
- Consumes: `RunManager`, heartbeat-правило из Task 5, `runner.main`.
- Produces:
  - `RunManager(mode="queue")`: `start()` делает те же проверки и создаёт `run.lock` с `{"run_id", "started", "mode": "queue"}`, но вместо `Popen` атомарно пишет заявку `<data>/web/requests/<run_id>.json` с `{"run_id"}`.
  - Режим выбирает переменная `AIDIGEST_RUN_MODE` (`local` по умолчанию или `queue`). Её читает `aidigest_web.__main__.main` и передаёт в `create_app(..., run_mode=...)`.
- Produces в `aidigest_web.worker`:
  - `POLL_SECONDS = 3`;
  - `process_once(data_dir: Path, run: Callable[[list[str]], int] = runner.main, before: Callable[[], None] = lambda: None, after: Callable[[int], None] = lambda code: None) -> str | None`. Берёт самую старую заявку и удаляет её файл. Если `run.lock` с этим `run_id` уже нет (веб пометил запуск прерванным), пропускает заявку. Иначе вызывает `before()`, `code = run([run_id])`, `after(code)` и возвращает `run_id`. Без заявок возвращает `None`.
  - `main(argv) -> int` — бесконечный цикл `process_once` с паузой `POLL_SECONDS`. `--status` печатает `busy` и возвращает 1, если `RunManager(...).current()` не `None`; иначе печатает `idle` и возвращает 0. Каталог данных — `AIDIGEST_DATA_DIR`, как в `runner`.

- [ ] **Step 1: Write the failing tests** в `tests/web/test_worker.py`:
  - `test_queue_start_writes_request_not_process`: `RunManager(mode="queue", popen=FakePopen())`, `start()` → `popen.calls == []`, файл заявки существует;
  - `test_process_once_runs_request`: после `start()` вызов `process_once(tmp_path, run=fake)` вызывает `fake([run_id])`, удаляет заявку и возвращает `run_id`;
  - `test_process_once_skips_cancelled_request`: заявка есть, `run.lock` удалён → `fake` не вызван, заявка удалена;
  - `test_process_once_without_requests`: → `None`;
  - `test_status_busy_and_idle`: монкипатчим `AIDIGEST_DATA_DIR` и проверяем код `main(["--status"])` при свежем heartbeat (1) и без запуска (0).
- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/web/test_worker.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `worker.py`, режим очереди в `RunManager`, передачу `run_mode` через `create_app`. Без переменной окружения поведение не меняется: существующие тесты `local`-режима проходят.
- [ ] **Step 4: Run** `.venv/Scripts/python -m pytest -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(web): worker берёт заявки на сбор из папки данных`.

### Task 7: Обслуживание — очистка и копии базы

**Files:**
- Create: `src/aidigest/housekeeping.py`
- Modify: `src/aidigest_web/worker.py` (`main` передаёт `before`/`after`)
- Test: `tests/test_housekeeping.py`, `tests/web/test_worker.py`

**Interfaces:**
- Produces в `aidigest.housekeeping`:
  - `CACHE_MAX_AGE_DAYS = {"tavily": 14, "llm": 180, "fetch": 180}`;
  - `prune_older_than(dir: Path, max_age_days: int, now: float) -> int` — удаляет файлы по mtime и возвращает их число;
  - `keep_newest(dir: Path, pattern: str, n: int) -> int` — сортирует по имени, оставляет последние `n`;
  - `prune_cache(data_dir: Path, now: float) -> int`;
  - `backup_cases(data_dir: Path, today: date) -> Path | None` — копирует `cases.json` в `<data>/backups/cases_<YYYY-MM-DD_HHMMSS>.json` и оставляет 30 последних. Если базы нет, возвращает `None`.
- Produces в `aidigest_web.worker`: `prune_runs(data_dir: Path, keep: int = 100) -> int` удаляет все файлы (`.json`, `.log`, `.heartbeat`) запусков старше 100 последних по `run_id`. `housekeep(data_dir)` = `prune_cache` + `prune_runs` + `keep_newest(out, "*.xlsx", 30)`. В `main` воркера `before=housekeep`, `after` = `backup_cases` при `code == 0`.

- [ ] **Step 1: Write the failing tests:**
  - `test_prune_cache_by_namespace`: в `cache/tavily` файл возрастом 15 дней удаляется, 13 дней — остаётся; в `cache/llm` файл возрастом 100 дней остаётся. Возраст задаётся через `os.utime`.
  - `test_keep_newest`: 35 файлов `cases_*.xlsx` → остаётся 30 самых новых по имени.
  - `test_backup_cases_keeps_30`.
  - `test_backup_without_base_returns_none`.
  - `test_prune_runs_removes_all_files_of_old_runs` (в `tests/web/test_worker.py`).
- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_housekeeping.py tests/web/test_worker.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** Очистка вызывается только из воркера. Локальный `aidigest run` её не делает.
- [ ] **Step 4: Run** `.venv/Scripts/python -m pytest -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: очистка кеша и логов, копия базы после каждого успешного сбора`.

### Task 8: Веб — `/healthz`, ограничение входа, режим за прокси

**Files:**
- Modify: `src/aidigest_web/auth.py`, `src/aidigest_web/routes.py`, `src/aidigest_web/__init__.py`, `src/aidigest_web/__main__.py`
- Modify: `src/aidigest_web/templates/login.html` (текст блокировки)
- Test: `tests/web/test_auth.py`, `tests/web/test_security.py`

**Interfaces:**
- Produces:
  - маршрут `GET /healthz` → `200`, тело `ok`, без входа (`"healthz"` в `OPEN_ENDPOINTS`);
  - `class LoginLimiter(max_failures: int = 10, window: float = 600, clock=time.monotonic)` с методами `blocked(ip: str) -> bool`, `failed(ip: str) -> None`, `reset(ip: str) -> None`. Хранится в `app.extensions["login_limiter"]`. Заблокированный вход отвечает 429 со страницей входа и текстом «Слишком много неудачных попыток. Подождите 10 минут.». Успешный вход сбрасывает счётчик.
  - `create_app(..., trust_proxy: bool = False)`. При `True` подключаются `ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)` и `SESSION_COOKIE_SECURE=True`. Включается переменной `AIDIGEST_TRUST_PROXY=1` (читает `__main__`).

- [ ] **Step 1: Write the failing tests:**
  - `test_healthz_open_without_login(protected_client)` → 200, `b"ok"`;
  - `test_login_blocked_after_10_failures(protected_client)`: 10 неверных попыток, затем верный пароль → 429;
  - `test_login_limiter_window_expires`: `LoginLimiter` с подменённым `clock`, через 601 с снова разрешено;
  - `test_trust_proxy_accepts_https_origin`: `create_app(..., password="p", secret_key="t", trust_proxy=True)`, POST `/login` с заголовками `X-Forwarded-Proto: https`, `Origin: https://localhost` → не 403.
- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/web -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** IP берётся из `request.remote_addr`. За прокси ProxyFix подставляет настоящий адрес клиента.
- [ ] **Step 4: Run** `.venv/Scripts/python -m pytest -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(web): /healthz, ограничение попыток входа, режим за HTTPS-прокси`.

### Task 9: Docker-образ, compose и `deploy.sh`

**Files:**
- Create: `requirements.lock`, `tools/lock_deps.sh`, `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `.env.example`, `deploy.sh`

**Interfaces:**
- Consumes:
  - `python -m aidigest_web` (переменные `AIDIGEST_DATA_DIR`, `AIDIGEST_RUN_MODE`, `AIDIGEST_TRUST_PROXY`, ключи из Task 1);
  - `python -m aidigest_web.worker` и `--status` (Task 6);
  - `/healthz` (Task 8).
- Produces: переменные compose в `.env` на сервере (пример — `.env.example`, `.env` уже в `.gitignore`):
  - `AIDIGEST_DATA_HOST=/srv/aidigest/data`;
  - `AIDIGEST_SECRETS=/srv/aidigest/secrets`;
  - `AIDIGEST_HTTP_PORT=80`;
  - `AIDIGEST_UID=1000`, `AIDIGEST_GID=1000`.

- [ ] **Step 1: Lock-файл.** `tools/lock_deps.sh` собирает чистое окружение в `python:3.13-slim` (`docker run --rm -v "$PWD":/src ...`), ставит `/src[web,dev]` и пишет `pip freeze` без строки `aidigest` в `requirements.lock`. Если Docker локально недоступен, первый `requirements.lock` получить командой `.venv/Scripts/python -m pip freeze --exclude-editable` и проверить, что в нём нет пакетов только для Windows, кроме `colorama` (она ставится и в Linux).
- [ ] **Step 2: `Dockerfile`.**
  - Основа: `python:3.13-slim`, `apt-get install -y --no-install-recommends tzdata`.
  - `ENV PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 PYTHONPATH=/app/src TZ=Asia/Yekaterinburg`, `WORKDIR /app`.
  - Сначала `COPY requirements.lock` и `pip install --no-cache-dir -r requirements.lock`, потом `COPY . .`.
  - Код лежит в `/app/src`, конфиги — в `/app/config`, потому что `ROOT = parents[2]`.
- [ ] **Step 3: `.dockerignore`** исключает `*.env`, `.env`, `.venv/`, `data/`, `Вводные данные/`, `.git/`, `.idea/`, `.superpowers/`, `__pycache__/`, `.pytest_cache/`.
- [ ] **Step 4: `docker-compose.yml`.**
  - Сервисы `web` и `worker` с общим `build: .`, `image: aidigest:latest` и `user: "${AIDIGEST_UID:-1000}:${AIDIGEST_GID:-1000}"`.
  - Том `${AIDIGEST_DATA_HOST:-/srv/aidigest/data}:/data`, `environment: AIDIGEST_DATA_DIR=/data, AIDIGEST_RUN_MODE=queue`.
  - `restart: unless-stopped`, `logging: json-file, max-size 10m, max-file 3`.
  - web:
    - `env_file: ${AIDIGEST_SECRETS}/web.env, ${AIDIGEST_SECRETS}/tavily.env` (Tavily нужен странице кредитов);
    - `ports: "${AIDIGEST_HTTP_PORT:-80}:8000"`, `command: python -m aidigest_web --host 0.0.0.0 --port 8000`;
    - healthcheck через `python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"`.
  - worker: `env_file: litellm.env, tavily.env`, `command: python -m aidigest_web.worker`.
- [ ] **Step 5: `deploy.sh`** (bash, `set -euo pipefail`). Флаг `--force`. Шаги:
  1. `git pull --ff-only`, при ошибке — сообщение «git pull не прошёл — на сервере есть локальные изменения?» и выход 1.
  2. `docker compose build`.
  3. `docker compose run --rm --no-deps -e AIDIGEST_DATA_DIR=/tmp/t web python -m pytest -q`. Если тесты упали, выход 1, контейнеры не трогаются.
  4. `docker compose up -d web`.
  5. Если `docker compose exec -T worker python -m aidigest_web.worker --status` говорит `busy` и нет `--force`, проверять каждые 15 секунд до 30 минут. Если сбор так и не закончился, печатается «Сайт обновлён, сборщик — нет: идёт сбор. Повторите ./deploy.sh позже или с --force.» и выход 1. Иначе `docker compose up -d worker`. Если worker не запущен, `--status` падает: это «не идёт».
  6. До 30 секунд ждать ответа `curl -fsS http://localhost:${AIDIGEST_HTTP_PORT:-80}/healthz` и напечатать «Выложено: <git rev-parse --short HEAD>».
- [ ] **Step 6: Проверка без сервера.** `docker compose config` проходит с `.env.example`, скопированным во временный `.env`. Если Docker доступен локально: `docker compose build` и `docker compose run --rm --no-deps web python -m pytest -q` → все PASS. Сбор при этом не запускать. Если Docker недоступен, честно записать это в отчёт задачи.
- [ ] **Step 7: Commit** `feat: Docker-образ, compose и deploy.sh`. Перед коммитом проверить `git status`: в коммит не попадают `.env` и `*.env`.

### Task 10: Данные вне git и документация

**Files:**
- Modify: `.gitignore`, `CLAUDE.md`, `README.md`
- Create: `docs/deploy.md`
- Remove from index: `data/cases.json`, `data/credits.json`

- [ ] **Step 1: `docs/deploy.md`.** Разделы:
  - **Первая установка:** Docker и пользователь в группе `docker`; клон по HTTPS или, для приватного репозитория, по read-only deploy key; `mkdir -p /srv/aidigest/{data,secrets}`; `chown -R 1000:1000 /srv/aidigest/data`; три env-файла в `secrets` с `chmod 600` и списком ключей без значений; `cp .env.example .env`; перенос `cases.json` и `credits.json` через `scp`; первый `./deploy.sh`.
  - **Выкладка:** `./deploy.sh`, что значит каждое сообщение, `--force`.
  - **Как скачать копию базы себе:** `scp` из `/srv/aidigest/data/cases.json` или `backups/`. Сервер — главный, обратно базу не заливать.
  - **Обновление зависимостей:** `tools/lock_deps.sh`.
  - **Когда появится домен:** блок Caddy для compose, `AIDIGEST_TRUST_PROXY=1`, закрыть порт 80 web наружу.
  - **Предупреждение команде:** перед `git pull` коммита из Step 2 скопировать `data/cases.json` и `data/credits.json`. Git удалит их из рабочей папки у тех, у кого они не изменены.
- [ ] **Step 2: Убрать данные из git.** `git rm --cached data/cases.json data/credits.json`, в `.gitignore` добавить `data/cases.json` и `data/credits.json`. Рабочие копии на диске остаются. Проверить: `git status` показывает удаление из индекса, а файлы есть в `data/`.
- [ ] **Step 3: CLAUDE.md и README.**
  - Строку «База кейсов — `data/cases.json` (в git)» заменить: «локально — `data/cases.json` (не в git); на сервере — `/srv/aidigest/data`, сервер — главный источник базы».
  - Добавить раздел «Сервер» со ссылкой на `docs/deploy.md`, командой `./deploy.sh` и переменными `AIDIGEST_RUN_MODE`, `AIDIGEST_TRUST_PROXY`.
  - В README — краткий раздел о выкладке со ссылкой.
- [ ] **Step 4: Финальная проверка.** `.venv/Scripts/python -m pytest -q` → PASS. `.venv/Scripts/python -m aidigest run --offline --budget 0` → код 0 и Excel. Локальный сайт через `.claude/launch.json` открывается: `/run` и `/healthz` отвечают, кнопку не нажимать.
- [ ] **Step 5: Commit** `chore: база кейсов вне git, инструкция по выкладке`.
