# Веб-фронт aiDigest — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** страница в браузере для «Аналитики»: список кейсов с фильтрами, карточка кейса, запуск сбора, справка, выгрузка Excel.

**Architecture:** отдельный пакет `src/aidigest_web` (Flask + Jinja2, сервер waitress). Из `aidigest` он только читает: модели, `CaseStore`, `export_xlsx`, `MonthlyUsage`, `load_settings`. Сбор запускается отдельным процессом через обёртку `aidigest_web.runner`, которая вызывает `python -m aidigest run`. Состояние запусков хранится в файлах `<data>/web/`.

**Tech Stack:** Python 3.13, Flask, Jinja2, waitress, свой CSS и чистый JS, pytest (Flask test client).

**Spec:** `docs/superpowers/specs/2026-11-07-web-frontend-design.md`

## Global Constraints

- `src/aidigest/` не меняется ни в одной задаче.
- Без JS- и CSS-фреймворков, без CDN и внешних шрифтов. Системный стек шрифтов.
- Без пароля сервер слушает только `127.0.0.1`; любой другой `--host` без `WEB_PASSWORD` — отказ с кодом выхода 2.
- Секреты (`*.env`) не попадают в шаблоны, логи и ответы.
- Тесты без сети и без настоящего пайплайна: `Popen` и проверка PID подменяются.
- Тесты фронта: `.venv/Scripts/python -m pytest tests/web -q`; весь набор: `.venv/Scripts/python -m pytest -q`.

## Review Focus

1. **Двойное нажатие «Запустить»** (два запроса почти одновременно) — стартует ровно один процесс, второй получает «сбор уже идёт». Тест — в задаче 4.
2. **Обёртка умерла, не записав итог** (процесс убит) — статус «прервано», lock снимается, кнопка снова доступна. Тест — в задаче 4.
3. **Месячный лимит исчерпан** — кнопка неактивна, POST тоже отклоняется. Тесты — в задачах 4 и 5.
4. **Пустая или отсутствующая база** (`cases.json` нет) — список показывает «кейсов пока нет», а не ошибку. Тест — в задаче 3.
5. **Кириллица и спецсимволы в поиске и в данных** (`<script>`, кавычки «») — экранируются шаблонами, фильтр работает без учёта регистра. Тест — в задаче 3.

---

## Структура файлов

```
src/aidigest_web/
  __init__.py      create_app
  __main__.py      запуск через waitress, проверка host/пароля
  auth.py          вход по общему паролю
  views.py         фильтры, главная цифра, тексты флагов (чистая логика)
  runs.py          RunManager: lock, старт, статус, история, разбор отчёта
  runner.py        обёртка: запускает aidigest run, пишет <run_id>.json
  routes.py        маршруты
  templates/       base, login, cases, case, run, help, 404
  static/style.css, static/app.js
tests/web/         conftest (app, client, фикстура базы), test_*.py
```

---

### Task 1: Каркас, вход, запуск сервера

**Files:** Create `src/aidigest_web/{__init__,__main__,auth,routes}.py`, `templates/{base,login}.html`, `static/style.css`, `tests/web/conftest.py`, `tests/web/test_auth.py`. Modify `pyproject.toml` (extra `web = ["flask", "waitress"]`), `.gitignore` (`secrets.env` уже покрыт `*.env` — проверить).

**Interfaces — Produces:**
- `create_app(data_dir: Path, password: str | None, secret_key: str | None = None, run_manager: RunManager | None = None) -> Flask`. `data_dir` и `run_manager` кладутся в `app.config["DATA_DIR"]` и `app.extensions["runs"]`.
- `auth.login_required` — before_request: если `password` задан и в сессии нет `auth`, то редирект на `/login?next=...`; `/login` и `/static/*` открыты.
- `__main__.main(argv) -> int`:
  - параметры `--host` (по умолчанию `127.0.0.1`) и `--port` (по умолчанию `8000`);
  - читает `secrets.env` из корня (`WEB_PASSWORD`, `WEB_SECRET_KEY`) через `aidigest.creds.load_env_file`, а также `AIDIGEST_DATA_DIR`;
  - host не из `127.0.0.1`/`localhost` при пустом пароле → печать причины, `return 2`;
  - иначе `waitress.serve(app, host, port)`.
- `conftest`:
  - фикстура `data_dir(tmp_path)` пишет `cases.json` с 3 кейсами: мир / регионы РФ / Свердловская обл.; с цифрами и без; подтверждено / один источник / с флагом `цифра_не_найдена_в_тексте`;
  - фикстуры `app` (без пароля) и `client`; `protected_client` (пароль `"секрет"`).

- [ ] **Step 1: Тесты.**
  - `test_pages_open_without_password` (GET `/` → 200);
  - `test_password_redirects_to_login` (GET `/` → 302 на `/login`);
  - `test_wrong_password_rejected` (POST `/login` неверный → 200 с текстом «Неверный пароль», в сессии нет auth);
  - `test_right_password_lets_in` (POST `/login` → 302, затем GET `/` → 200);
  - `test_main_refuses_network_without_password` (`main(["--host","0.0.0.0"])` с пустым паролем → 2, waitress не вызывался — подменён через monkeypatch).
- [ ] **Step 2: Запустить.** Ожидается FAIL (ImportError). **Step 3: Реализовать.** `/` пока может отдавать заглушку на `base.html`. **Step 4: Запустить.** Ожидается PASS. Установить extra: `.venv/Scripts/python -m pip install -e ".[web,dev]"`.
- [ ] **Step 5: Commit** `feat(web): каркас фронта, вход по паролю, запуск через waitress`.

### Task 2: Логика представления (без HTTP)

**Files:** Create `src/aidigest_web/views.py`, `tests/web/test_views.py`.

**Interfaces — Produces:**
- `DOUBTFUL = {Flag.QUOTE_NOT_FOUND, Flag.SOURCES_CONFLICT}`.
- `filter_cases(cases: list[Case], q: str = "", level: str = "", status: str = "", with_metrics: bool = True, hide_doubtful: bool = False) -> list[Case]`:
  - `q` ищется без учёта регистра и «ё» в title, summary, region, organization, ai_technology, municipality, country;
  - `level` и `status` сравниваются со значениями enum; пустая строка — без фильтра.
  - Результат отсортирован как в Excel: с метриками → по статусу (подтверждено, противоречие, один_источник) → по уровню.
- `headline(case: Case) -> tuple[str, bool]`: возвращает (текст, сомнительна ли).
  - Первая метрика с `quote_verified` → `(metric_line, False)`.
  - Метрики есть, но ни одна не проверена → `(metric_line первой, True)`.
  - Метрик нет → `("—", False)`. `metric_line` — из `aidigest.export_excel`.
- `FLAG_HELP: dict[Flag, tuple[str, str]]` — («что значит», «что делать») для всех 7 флагов, тексты из README.
- `STATUS_CLASS: dict[ConfirmationStatus, str]` — `"ok"`, `"warn"`, `"bad"`.

- [ ] **Step 1: Тесты.**
  - `test_default_filter_keeps_only_cases_with_metrics`;
  - `test_search_is_case_insensitive_and_yo_insensitive` («ЕКАТЕРИНБУРГ», «ё» против «е»);
  - `test_level_and_status_filters`;
  - `test_hide_doubtful_drops_flagged`;
  - `test_sort_matches_excel_order`;
  - `test_headline_prefers_verified_metric`;
  - `test_headline_marks_unverified`;
  - `test_headline_dash_without_metrics`;
  - `test_flag_help_covers_all_flags` (`set(FLAG_HELP) == set(Flag)`).
- [ ] **Step 2–4:** FAIL → реализовать → PASS. **Step 5: Commit** `feat(web): фильтры, главная цифра, пояснения флагов`.

### Task 3: Страницы «Кейсы», карточка, справка, Excel

**Files:** Modify `routes.py`. Create `templates/{cases,case,help,404}.html`, `tests/web/test_pages.py`.

**Interfaces — Consumes:** `filter_cases`, `headline`, `FLAG_HELP`, `STATUS_CLASS` (задача 2), `CaseStore`, `export_xlsx`.

**Маршруты:**
- `GET /` — параметры `q`, `level`, `status`, `metrics` (`"1"` по умолчанию; форма передаёт `"0"`, если галочка снята), `doubtful`. Строка «Найдено N из M · база обновлена ДД.ММ.ГГГГ ЧЧ:ММ» (mtime `cases.json`).
- `GET /case/<id>` — карточка; неизвестный id → 404-шаблон.
- `GET /help`.
- `GET /export.xlsx` — `export_xlsx` во временный файл, `send_file(..., download_name="aidigest_cases_<YYYY-MM-DD>.xlsx")`.

- [ ] **Step 1: Тесты.**
  - `test_list_shows_counts_and_rows`;
  - `test_list_filters_via_query`;
  - `test_empty_base_shows_placeholder` (нет `cases.json` → 200 и «Кейсов пока нет»);
  - `test_html_is_escaped` (кейс с title `<script>alert(1)</script>` → в ответе `&lt;script&gt;`);
  - `test_case_card_shows_quote_source_and_flags`;
  - `test_unknown_case_is_404`;
  - `test_help_lists_all_flags`;
  - `test_export_returns_xlsx` (заголовок `Content-Disposition` с `aidigest_cases_`, `openpyxl` открывает тело).
- [ ] **Step 2–4:** FAIL → реализовать → PASS. **Step 5: Commit** `feat(web): страницы кейсов, карточка, справка, выгрузка Excel`.

### Task 4: Управление запусками и обёртка

**Files:** Create `src/aidigest_web/runs.py`, `src/aidigest_web/runner.py`, `tests/web/test_runs.py`.

**Interfaces — Produces:**
- `RunInfo` (dataclass): `run_id: str`, `started: datetime`, `finished: datetime | None`, `exit_code: int | None`, `state: Literal["running","ok","error","limit","interrupted"]`, `log_path: Path`, `report: dict[str, str]`.
- `parse_report(log_text: str) -> dict[str, str]` — строки `Ключ: значение` для ключей из отчёта CLI (начинаются с «Кредитов», «Вызовов», «Статей», «Кандидатов», «Кейсов», «Подтверждений», «Бюджет», «Флаг:»).
- `RunManager(data_dir: Path, project_root: Path, popen=subprocess.Popen, pid_alive: Callable[[int], bool] = default_pid_alive, now: Callable[[], datetime] = datetime.now)`:
  - `.current() -> RunInfo | None` — читает `run.lock`. Если есть `<run_id>.json` → снимает lock и возвращает None. Если PID мёртв и json нет → пишет json с `state="interrupted"`, снимает lock, возвращает None.
  - `.start() -> RunInfo`:
    - `MonthExhausted`, если `MonthlyUsage(...).remaining(today) <= 0`;
    - `AlreadyRunning`, если `current()` не None или lock создать не удалось (`os.open(O_CREAT|O_EXCL)`);
    - иначе Popen обёртки: `[sys.executable, "-m", "aidigest_web.runner", run_id]` с `cwd=project_root`, env с `AIDIGEST_DATA_DIR`, creationflags `CREATE_NEW_PROCESS_GROUP|DETACHED_PROCESS` в Windows или `start_new_session=True` в Linux; stdout/stderr → DEVNULL (лог пишет обёртка);
    - записывает в lock PID и старт.
  - `.history(limit=10) -> list[RunInfo]` — из `runs/*.json`, свежие первыми.
  - `.tail(run: RunInfo, lines=30) -> list[str]`.
- `default_pid_alive(pid) -> bool` — Windows: `ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)` + `GetExitCodeProcess == 259`; иначе `os.kill(pid, 0)`.
- `runner.main(argv) -> int` — `run_id` из аргумента, data_dir из `AIDIGEST_DATA_DIR` или `data`:
  - пишет стартовый json `{"started": ...}`;
  - выполняет `subprocess.run([sys.executable, "-m", "aidigest", "run"], stdout=log, stderr=STDOUT, env=... PYTHONIOENCODING=utf-8)`;
  - пишет итоговый json: `finished`, `exit_code`, `state` (0 → ok, 2 → limit, иное → error).

  Чтобы `current()` отличал «идёт» от «закончился», json-итог пишется в `<run_id>.json`, а стартовая метка — в lock.

- [ ] **Step 1: Тесты** (`popen` и `pid_alive` — фейки, время — фиксированное):
  - `test_start_creates_lock_and_spawns_runner` (аргументы Popen содержат `aidigest_web.runner`, cwd — корень);
  - `test_second_start_is_rejected` (Review Focus 1);
  - `test_finished_run_releases_lock` (появился json → `current()` None, `history()[0].state == "ok"`);
  - `test_dead_pid_without_result_is_interrupted` (Review Focus 2);
  - `test_month_exhausted_blocks_start` (`credits.json` = лимит → `MonthExhausted`);
  - `test_parse_report_reads_cli_lines`;
  - `test_runner_writes_result_json` (подменить `subprocess.run`, вернуть returncode 2 → state `limit`).
- [ ] **Step 2–4:** FAIL → реализовать → PASS. **Step 5: Commit** `feat(web): запуски сбора — блокировка, обёртка, история`.

### Task 5: Страница запуска и опрос статуса

**Files:** Modify `routes.py`. Create `templates/run.html`, `static/app.js`, `tests/web/test_run_page.py`.

**Маршруты:**
- `GET /run` — кредиты месяца (`MonthlyUsage`, `load_settings`), кнопка, текущий запуск с хвостом лога, итог последнего, история.
- `POST /run` — `start()`. `AlreadyRunning` и `MonthExhausted` → редирект на `/run` с сообщением (flash).
- `GET /run/status` — JSON `{"running": bool, "started": iso | null, "minutes": int, "tail": [str]}`.

`app.js`:
- сортировка таблиц по клику на `th[data-sort]` (числа и текст, `localeCompare` с `ru`);
- на `/run`, если есть `[data-running]`, опрос `/run/status` раз в 5 с: обновление хвоста лога, при `running: false` — `location.reload()`.

- [ ] **Step 1: Тесты:**
  - `test_run_page_shows_credits_and_button`;
  - `test_post_run_starts_once` (второй POST → сообщение «Сбор уже идёт»);
  - `test_button_disabled_when_month_exhausted` (атрибут `disabled` и POST отклоняется — Review Focus 3);
  - `test_status_json_while_running`;
  - `test_history_shows_last_report`.
- [ ] **Step 2–4:** FAIL → реализовать → PASS. **Step 5: Commit** `feat(web): страница запуска сбора с автообновлением`.

### Task 6: Внешний вид, проверка в браузере, документация

**Files:** Modify `static/style.css`, шаблоны, `README.md` (раздел «Веб-интерфейс»), `CLAUDE.md` (строка о фронте и `secrets.env`).

- [ ] **Step 1: Довести стили.**
  - CSS-переменные палитры, шапка, карточки, «таблетки» статусов, липкая шапка таблиц, hover, фокус-обводка, ширина контента до ~1200px;
  - на экране шириной 375px страница не ломается (таблица прокручивается горизонтально внутри контейнера).
- [ ] **Step 2: Запустить сервер.** `.venv/Scripts/python -m aidigest_web` в фоне на реальной базе. Пройти в встроенном браузере все страницы, сделать скриншоты и поправить вёрстку. Кнопку запуска при проверке **не нажимать** — это расход кредитов. Запуск уже покрыт тестами.
- [ ] **Step 3: Документация.** README: установка `[web]`, `secrets.env`, запуск, доступ по сети только с паролем, предупреждение «не запускать сбор из консоли, пока идёт запуск с сайта», как удалить фронт.
- [ ] **Step 4: Весь набор тестов** `.venv/Scripts/python -m pytest -q` — PASS. Проверить, что `git diff master -- src/aidigest` пуст.
- [ ] **Step 5: Commit** `feat(web): оформление и документация`.
