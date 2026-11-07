# Пайплайн сбора кейсов внедрения ИИ — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** одна консольная команда выполняет регулярный цикл: поиск статей → извлечение кейсов LLM → проверка цитат → подтверждение вторым источником → дедупликация → база JSON → Excel.

**Architecture:** пакет `aidigest` (src-layout). Внешние сервисы (Tavily, LiteLLM, HTTP) спрятаны за протоколами `SearchClient` / `LLMClient` с дисковым кешем, поэтому вся логика тестируется фейками без сети. Флаги и статус кейса вычисляются из его данных детерминированно. Бюджет Tavily — объект с двумя пулами (сбор / подтверждение).

**Tech Stack:** Python 3.13, pydantic 2, openai SDK (для LiteLLM Proxy), tavily-python, PyYAML, openpyxl, requests + trafilatura (только для эталона), pytest.

**Spec:** `docs/superpowers/specs/2026-11-07-ai-cases-pipeline-design.md`

## Global Constraints

- **`litellm.env` и `tavily.env` никогда не открывать и не выводить.** Код загружает их в рантайме через `aidigest.creds.load_env_file`. Ключи: `LITELLM_API_KEY`, `LITELLM_BASE_URL`, `LITELLM_MODEL` (по умолчанию `GigaChat-3-Pro`), `TAVILY_TOKEN`.
- Tavily: 1000 кредитов в месяц на всё. Регулярный запуск — около 30 кредитов, первый запуск — до 100. Резерв под подтверждение — 40%. Внешние вызовы Tavily и LLM только в задачах 12–13; в остальных задачах — фейки.
- Тесты не ходят в сеть.
- Все ответы Tavily, LLM и HTTP кешируются на диск. Повторный прогон на тех же данных не тратит ни кредитов, ни вызовов LLM.
- Показатель без дословной цитаты недопустим. Цитата не найдена в тексте → флаг `цифра_не_найдена_в_тексте`.
- Всё в UTF-8. В CLI при старте вызывать `sys.stdout.reconfigure(encoding="utf-8")`. Пути с кириллицей — через `pathlib`.
- Значения перечислений и заголовки Excel — по-русски, как в спеке. Идентификаторы кода — по-английски.
- Команды запуска тестов: `.venv/Scripts/python -m pytest …` (Windows, Git Bash).

## Review Focus

1. **URL с UTM-метками и якорями** (в списке «Аналитики» есть `?utm_source=chatgpt.com`) — это та же страница: повторно в LLM не уходит, дублем источника не становится. Тест — в задаче 2.
2. **Кириллические домены** (`нацпроекты.рф` приходит как `xn--…`) — находятся в справочнике и получают достоверность. Тест — в задаче 4.
3. **LLM ответила прозой, JSON в ```-блоке или битым JSON.** Блок разбирается. Битый ответ — один повтор, потом статья пропускается без падения запуска и не помечается обработанной (повтор в следующий раз). Тесты — в задачах 5 и 11.
4. **Бюджет кончился посреди сбора.** Уже собранное обработано и сохранено, кейсы получают `подтверждение_не_проводилось`, запуск завершается штатно с отчётом. Тест — в задаче 11.
5. **Падение во время записи базы** — старый `data/cases.json` остаётся целым (запись через временный файл + `os.replace`). Тест — в задаче 9.

---

## Структура файлов

```
pyproject.toml
config/sources.yaml          справочник источников
config/queries.yaml          поисковые запросы по уровням
config/settings.yaml         бюджеты, окна, лимиты
eval/reference_cases.yaml    эталон (URL + ожидаемые цифры)
eval/texts/                  ручные тексты статей, если HTTP не скачал
data/cases.json              база кейсов (в git)
data/cache/, data/out/       кеш и выгрузки (в .gitignore)
src/aidigest/
  __init__.py  __main__.py   (__main__ вызывает cli.main)
  models.py      перечисления, Metric, Source, Article, Case
  creds.py       load_env_file
  urls.py        normalize_url, domain_of
  cache.py       DiskCache
  budget.py      CreditBudget, BudgetExceeded
  quotes.py      нормализация текста/чисел, проверка цитат
  registry.py    SourceInfo, SourceRegistry
  config.py      Settings, QuerySpec, загрузка YAML
  llm.py         LLMClient, LiteLLMClient, parse_json_reply
  methodology.py критерии методик, выбор методики
  extract.py     extract_cases
  search.py      SearchClient, TavilySearch
  confirm.py     очередь и подтверждение
  dedup.py       поиск дубля и слияние
  store.py       CaseStore
  export_excel.py
  pipeline.py    run_cycle, RunReport
  fetch.py       fetch_text (эталон)
  evaluate.py    run_eval
  cli.py
tests/test_<модуль>.py, tests/fakes.py
```

---

### Task 1: Каркас проекта, модели, загрузка кредов

**Files:**
- Create: `pyproject.toml`, `src/aidigest/__init__.py`, `src/aidigest/models.py`, `src/aidigest/creds.py`, `tests/test_models.py`, `tests/test_creds.py`
- Modify: `.gitignore` (добавить `data/cache/`, `data/out/`, `*.egg-info/`)

**Interfaces:**
- Produces (`models.py`, перечисления — `StrEnum`, значения дословно):
  - `Level`: `WORLD="мир"`, `RF_REGIONS="регионы РФ"`, `SVERDLOVSK="Свердловская область"`
  - `Sector`: `GOV="госсектор"`, `BUSINESS="бизнес"`
  - `Stage`: `UNKNOWN="неизвестно"`, `DEVELOPMENT="в разработке"`, `PILOT="пилот"`, `DEPLOYED="внедрён"`, `SCALING="масштабирование"` (порядок объявления = порядок «зрелости»)
  - `MetricKind`: `FACT="факт"`, `PLAN="план"`
  - `Reliability`: `HIGH="высокая"`, `MEDIUM="средняя"`, `LOW="низкая"`, `UNRATED="не_оценена"`
  - `SourceType`: `OFFICIAL="официальная"`, `STATISTICS="статистика"`, `CASES="кейсы"`, `MARKET="аналитика рынка"`, `MEDIA="СМИ"`, `UNKNOWN="неизвестно"`
  - `Methodology`: `M1="М-1"`, `R1="Р-1"`, `BUSINESS="бизнес-метрики"`
  - `ConfirmationStatus`: `CONFIRMED="подтверждено"`, `CONFLICT="противоречие"`, `SINGLE="один_источник"`
  - `Flag`: `QUOTE_NOT_FOUND="цифра_не_найдена_в_тексте"`, `SOURCES_CONFLICT="противоречие_источников"`, `SINGLE_SOURCE="один_источник"`, `STAGE_UNCLEAR="стадия_неясна"`, `NO_METRICS="нет_измеримых_показателей"`, `SOURCE_UNRATED="источник_не_оценён"`, `CONFIRMATION_SKIPPED="подтверждение_не_проводилось"`
- Produces (pydantic-модели):
  - `Metric(name: str, criterion: str, before: str|None, after: str|None, change: str|None, unit: str|None, kind: MetricKind, quote: str, source_url: str, quote_verified: bool = False, confirmed_by: list[str] = [], conflicting_values: list[str] = [])`
  - `Source(url: str, domain: str, title: str = "", published_at: str|None = None, reliability: Reliability = UNRATED, source_type: SourceType = UNKNOWN)`
  - `Article(url: str, domain: str, title: str, text: str, published_at: str|None = None)`
  - `Case(id: str, first_seen: date, updated: date, level: Level, country: str, region: str|None, municipality: str|None, organization: str|None, sector: Sector, industry: str, ai_technology: str, title: str, summary: str, stage: Stage, methodology: Methodology, metrics: list[Metric], sources: list[Source], confirmation_status: ConfirmationStatus = SINGLE, confirmation_attempts: int = 0, last_confirmation_attempt: date|None = None)`
  - `Case.flags` — `@computed_field`, `list[Flag]`, сериализуется в JSON. Правила:
    - `QUOTE_NOT_FOUND` — есть метрика с `quote_verified=False`;
    - `NO_METRICS` — метрик нет;
    - `STAGE_UNCLEAR` — `stage==UNKNOWN`;
    - `SOURCE_UNRATED` — есть источник с `UNRATED`;
    - `SOURCES_CONFLICT` — `status==CONFLICT`;
    - `SINGLE_SOURCE` — `status==SINGLE` и `attempts>0`;
    - `CONFIRMATION_SKIPPED` — метрики есть и `attempts==0`.
  - `Case.recompute_status() -> None`: `CONFLICT`, если у какой-то метрики есть `conflicting_values`; иначе `CONFIRMED`, если есть непустой `confirmed_by`; иначе `SINGLE`.
- Produces: `creds.load_env_file(path: Path) -> dict[str, str]` — логика как в `test_litellm.py`; отсутствующий файл → `FileNotFoundError`.

- [ ] **Step 1: Создать `.venv` и `pyproject.toml`.** `python -m venv .venv`; зависимости: `openai pydantic pyyaml openpyxl tavily-python requests trafilatura`, extra `dev = ["pytest"]`; `[tool.pytest.ini_options] pythonpath=["src"]`. Затем `.venv/Scripts/python -m pip install -e ".[dev]"`.
- [ ] **Step 2: Написать падающие тесты.**

```python
def test_flags_for_fresh_case_with_unverified_metric(make_case, make_metric):
    c = make_case(metrics=[make_metric(quote_verified=False)], stage=Stage.UNKNOWN)
    assert set(c.flags) == {Flag.QUOTE_NOT_FOUND, Flag.STAGE_UNCLEAR, Flag.CONFIRMATION_SKIPPED}

def test_no_metrics_case_has_no_confirmation_flags(make_case):
    c = make_case(metrics=[], stage=Stage.PILOT)
    assert c.flags == [Flag.NO_METRICS]

def test_recompute_status_conflict_wins(make_case, make_metric):
    c = make_case(metrics=[make_metric(confirmed_by=["https://a.ru/1"]),
                           make_metric(conflicting_values=["161 (https://b.ru)"])])
    c.recompute_status()
    assert c.confirmation_status == ConfirmationStatus.CONFLICT and Flag.SOURCES_CONFLICT in c.flags

def test_case_json_roundtrip_keeps_russian_values(make_case):
    c = make_case()
    raw = c.model_dump_json()
    assert "Свердловская область" in raw or "регионы РФ" in raw
    assert Case.model_validate_json(raw) == c

def test_load_env_file_parses_quotes_and_comments(tmp_path):
    p = tmp_path / "x.env"; p.write_text('# c\nA="1"\nB=\'2\'\nbad\n', encoding="utf-8")
    assert load_env_file(p) == {"A": "1", "B": "2"}
```

Фабрики `make_case` и `make_metric` — фикстуры в `tests/conftest.py` с разумными значениями по умолчанию. Они используются во всех следующих задачах.

- [ ] **Step 3: Запустить** `.venv/Scripts/python -m pytest tests/test_models.py tests/test_creds.py -v`. Ожидается FAIL (ImportError).
- [ ] **Step 4: Реализовать `models.py`, `creds.py`.**
- [ ] **Step 5: Запустить те же тесты.** Ожидается PASS.
- [ ] **Step 6: Commit** `feat: каркас проекта, модели кейса, загрузка кредов`.

---

### Task 2: URL, дисковый кеш, бюджет кредитов

**Files:**
- Create: `src/aidigest/urls.py`, `src/aidigest/cache.py`, `src/aidigest/budget.py`, `tests/test_urls.py`, `tests/test_cache.py`, `tests/test_budget.py`

**Interfaces:**
- Produces:
  - `normalize_url(url: str) -> str` — убирает `utm_*`, `fbclid`, `yclid`, `#фрагмент`, завершающий `/`; хост в нижнем регистре и в Unicode (IDNA-декод).
  - `domain_of(url: str) -> str` — хост без `www.`, в Unicode.
  - `DiskCache(root: Path)`:
    - `.get(namespace: str, key: Any) -> Any | None`;
    - `.put(namespace: str, key: Any, value: Any) -> None`;
    - файл `root/namespace/<sha256(json.dumps(key, sort_keys=True, ensure_ascii=False))>.json`, атомарная запись.
  - `class BudgetExceeded(Exception)`.
  - `CreditBudget(total: float, confirm_share: float = 0.4)`:
    - `.can_spend(pool: Literal["collect","confirm"], cost: float) -> bool`;
    - `.spend(pool, cost) -> None` (не хватает → `BudgetExceeded`);
    - `.remaining(pool) -> float`;
    - `.spent -> float`;
    - `.close_collection() -> None` переносит остаток сбора в пул подтверждения. Обратного переноса нет (спека).

- [ ] **Step 1: Написать падающие тесты.**

```python
def test_normalize_url_drops_tracking():
    a = normalize_url("https://digitalservice.bund.de/en/projects/agentic-ai-hub?utm_source=chatgpt.com#top")
    assert a == "https://digitalservice.bund.de/en/projects/agentic-ai-hub"
    assert normalize_url("https://WWW.Example.com/a/?id=5&utm_medium=x") == "https://www.example.com/a?id=5"

def test_domain_of_decodes_punycode():
    assert domain_of("https://xn--80akpjgfht4a0d.xn--p1ai/news/1") == "нацпроекты.рф"
    assert domain_of("https://www.chel.kp.ru/x") == "chel.kp.ru"

def test_cache_roundtrip_cyrillic(tmp_path):
    c = DiskCache(tmp_path); c.put("llm", {"q": "кейс"}, {"a": "ответ"})
    assert c.get("llm", {"q": "кейс"}) == {"a": "ответ"} and c.get("llm", {"q": "другое"}) is None

def test_budget_pools():
    b = CreditBudget(30)
    assert b.remaining("collect") == 18 and b.remaining("confirm") == 12
    for _ in range(18): b.spend("collect", 1)
    with pytest.raises(BudgetExceeded): b.spend("collect", 1)
    b.close_collection(); assert b.remaining("confirm") == 12 and b.spent == 18

def test_budget_leftover_collect_moves_to_confirm():
    b = CreditBudget(10); b.spend("collect", 2); b.close_collection()
    assert b.remaining("confirm") == 8
```

- [ ] **Step 2: Запустить.** Ожидается FAIL.
- [ ] **Step 3: Реализовать** три модуля. Для URL — `urllib.parse`, для punycode — `host.encode().decode("idna")` по частям.
- [ ] **Step 4: Запустить.** Ожидается PASS.
- [ ] **Step 5: Commit** `feat: нормализация URL, дисковый кеш, бюджет Tavily`.

---

### Task 3: Проверка цитат и чисел

**Files:**
- Create: `src/aidigest/quotes.py`, `tests/test_quotes.py`

**Interfaces:**
- Consumes: `Metric`.
- Produces:
  - `normalize_text(s: str) -> str`: нижний регистр, `ё→е`, неразрывные и узкие пробелы → пробел, кавычки `«»“”„"` → `"`, тире `—–−` → `-`, схлопывание пробелов.
  - `extract_numbers(s: str) -> list[float]`:
    - десятичная запятая или точка;
    - пробелы внутри числа («9 000 000»);
    - множители `тыс`, `млн`, `млрд`, `трлн` сразу после числа (умножают).
  - `quote_in_text(quote: str, text: str) -> bool`: подстрока после `normalize_text`. Если не нашлось — повторить, выбросив из обеих строк всю пунктуацию.
  - `numbers_in_quote(metric: Metric) -> bool`: каждое число из `before`/`after`/`change` есть среди `extract_numbers(quote)` (допуск 1e-6, относительный 1e-3).
  - `verify_metric(metric: Metric, text: str) -> bool` = `quote_in_text(...) and numbers_in_quote(...)`.

- [ ] **Step 1: Написать падающие тесты** (цифры — из эталона «рос и рег»).

```python
TEXT = "По данным ведомства, среднее время в пробках сократилось с 13 до 5 минут, а экономия бюджета — более 9 млн руб."

def test_extract_numbers_russian_formats():
    assert extract_numbers("в 2,5 раза") == [2.5]
    assert extract_numbers("9 000 000 руб") == [9_000_000]
    assert extract_numbers("более 9 млн руб.") == [9_000_000]
    assert extract_numbers("со 161 до 122") == [161, 122]
    assert extract_numbers("свыше 90%") == [90]

def test_quote_found_despite_nbsp_and_dash():
    assert quote_in_text("сократилось с 13 до 5 минут", TEXT)
    assert quote_in_text("экономия бюджета - более 9 млн руб", TEXT)

def test_verify_metric_rejects_invented_number(make_metric):
    ok = make_metric(before="13 мин", after="5 мин", quote="сократилось с 13 до 5 минут")
    bad = make_metric(before="13 мин", after="4 мин", quote="сократилось с 13 до 5 минут")
    assert verify_metric(ok, TEXT) and not verify_metric(bad, TEXT)

def test_verify_metric_rejects_quote_absent_from_text(make_metric):
    m = make_metric(change="-24%", quote="число ДТП снизилось на 24%")
    assert not verify_metric(m, TEXT)

def test_million_equivalence(make_metric):
    m = make_metric(change="9 000 000 руб", quote="более 9 млн руб")
    assert numbers_in_quote(m)
```

- [ ] **Step 2: Запустить** `.venv/Scripts/python -m pytest tests/test_quotes.py -v`. Ожидается FAIL.
- [ ] **Step 3: Реализовать `quotes.py`.** `extract_numbers` знак не учитывает и всегда возвращает модули: «−23%» и «23%» → `[23]`. Иначе «снижено на 23%» не совпадёт с `change="-23%"`.
- [ ] **Step 4: Запустить.** Ожидается PASS.
- [ ] **Step 5: Commit** `feat: проверка цитат и чисел показателей`.

---

### Task 4: Справочник источников (вкл. Свердловскую область)

**Files:**
- Create: `config/sources.yaml`, `src/aidigest/registry.py`, `tests/test_registry.py`

**Interfaces:**
- Consumes: `Level`, `Reliability`, `SourceType`, `domain_of`.
- Produces:
  - `SourceInfo(name: str, domains: list[str], level: Level|None, reliability: Reliability, source_type: SourceType, update_frequency: str)` (pydantic);
  - `SourceRegistry.load(path: Path) -> SourceRegistry`;
  - `.lookup(url: str) -> SourceInfo | None` — точное совпадение домена или родительского (`chel.kp.ru` найдёт запись `kp.ru`);
  - `.domains_for(level: Level) -> list[str]`;
  - `.to_source(article: Article) -> Source` — неизвестный домен → `UNRATED`/`UNKNOWN`.

- [ ] **Step 1: Найти источники по Свердловской области** через WebSearch/браузер, **не через Tavily**. Нужно 5–10 доменов: официальный портал области, Минцифры области, портал Екатеринбурга, региональные деловые СМИ (например, e1.ru, ura.ru, oblgazeta.ru, URA/«Деловой квартал» — проверить, что публикуют материалы о цифровизации). Для каждого проверить, что сайт живой.
- [ ] **Step 2: Заполнить `config/sources.yaml`.**
  - Все источники из `Вводные данные/md/` — с достоверностью, типом и частотой оттуда. Reuters — `средняя`, «Цифровой регион» — `средняя` (решения спеки).
  - Региональные СМИ эталона: `gubernia74.ru`, `kp.ru`, `rbc.ru`, `itrussia.media`, `нацпроекты.рф`, `realnoevremya.ru` — `средняя`, `СМИ`; `нацпроекты.рф` — `высокая`, `официальная`.
  - Свердловские источники из шага 1.
- [ ] **Step 3: Написать падающие тесты.**

```python
def test_real_registry_loads_and_covers_all_levels():
    r = SourceRegistry.load(Path("config/sources.yaml"))
    for lvl in Level: assert r.domains_for(lvl), lvl

def test_lookup_cyrillic_punycode_and_parent():
    r = SourceRegistry.load(Path("config/sources.yaml"))
    assert r.lookup("https://xn--80akpjgfht4a0d.xn--p1ai/x").reliability == Reliability.HIGH
    assert r.lookup("https://chel.kp.ru/daily/1").source_type == SourceType.MEDIA

def test_reuters_is_medium():
    r = SourceRegistry.load(Path("config/sources.yaml"))
    assert r.lookup("https://www.reuters.com/technology/artificial-intelligence/x").reliability == Reliability.MEDIUM

def test_unknown_domain_becomes_unrated():
    r = SourceRegistry.load(Path("config/sources.yaml"))
    s = r.to_source(Article(url="https://unknown-blog.ru/a", domain="unknown-blog.ru", title="t", text=""))
    assert s.reliability == Reliability.UNRATED
```

- [ ] **Step 4: Запустить.** Ожидается FAIL. **Step 5: Реализовать `registry.py`.** **Step 6: Запустить.** Ожидается PASS.
- [ ] **Step 7: Commit** `feat: справочник источников, включая Свердловскую область`.

---

### Task 5: LLM-клиент и разбор JSON

**Files:**
- Create: `src/aidigest/llm.py`, `tests/fakes.py`, `tests/test_llm.py`

**Interfaces:**
- Consumes: `DiskCache`.
- Produces:
  - `class LLMFormatError(Exception)`, `class OfflineCacheMiss(Exception)`.
  - `parse_json_reply(text: str) -> Any`: снимает ```json-обёртку; иначе берёт подстроку от первой `{`/`[` до парной последней; не вышло → `ValueError`.
  - `class LLMClient(Protocol): def complete_json(self, system: str, user: str) -> Any`.
  - `LiteLLMClient(api_key: str|None, base_url: str|None, model: str, cache: DiskCache, offline: bool = False, client: Any = None)`:
    - `client` — объект с интерфейсом `openai.OpenAI` (для тестов подставляется фейк);
    - `temperature=0`;
    - кеш по ключу `{"model","system","user"}`;
    - ошибка разбора → один повтор с допиской «Ответ должен быть только корректным JSON без пояснений.», второй провал → `LLMFormatError`;
    - `offline` и промах кеша → `OfflineCacheMiss`;
    - счётчик `.calls: int` — только реальные вызовы.
- Produces (`tests/fakes.py`): `FakeLLM(replies: list[Any] | Callable[[str, str], Any])` — `complete_json` и `.calls`; `FakeOpenAI(texts: list[str])` — имитирует `client.chat.completions.create(...).choices[0].message.content`.

- [ ] **Step 1: Написать падающие тесты.**

```python
def test_parse_fenced_and_prose():
    assert parse_json_reply('Вот ответ:\n```json\n{"cases": []}\n```') == {"cases": []}
    assert parse_json_reply('Результат: {"a": [1, 2]} конец') == {"a": [1, 2]}

def test_retry_once_then_success(tmp_path):
    llm = LiteLLMClient(None, None, "m", DiskCache(tmp_path), client=FakeOpenAI(["не json", '{"ok": true}']))
    assert llm.complete_json("s", "u") == {"ok": True} and llm.calls == 2

def test_two_bad_replies_raise(tmp_path):
    llm = LiteLLMClient(None, None, "m", DiskCache(tmp_path), client=FakeOpenAI(["нет", "снова нет"]))
    with pytest.raises(LLMFormatError): llm.complete_json("s", "u")

def test_cache_hit_makes_no_call(tmp_path):
    cache = DiskCache(tmp_path)
    LiteLLMClient(None, None, "m", cache, client=FakeOpenAI(['{"x": 1}'])).complete_json("s", "u")
    again = LiteLLMClient(None, None, "m", cache, client=FakeOpenAI([]))
    assert again.complete_json("s", "u") == {"x": 1} and again.calls == 0

def test_offline_miss(tmp_path):
    with pytest.raises(OfflineCacheMiss):
        LiteLLMClient(None, None, "m", DiskCache(tmp_path), offline=True, client=FakeOpenAI([])).complete_json("s", "u")
```

- [ ] **Step 2: Запустить.** Ожидается FAIL. **Step 3: Реализовать.** Если `client is None`, создать `openai.OpenAI(api_key=..., base_url=...)`. **Step 4: Запустить.** Ожидается PASS.
- [ ] **Step 5: Commit** `feat: LLM-клиент с кешем и повтором при битом JSON`.

---

### Task 6: Методики и извлечение кейсов

**Files:**
- Create: `src/aidigest/methodology.py`, `src/aidigest/extract.py`, `tests/test_methodology.py`, `tests/test_extract.py`

**Interfaces:**
- Consumes: `LLMClient`, `SourceRegistry.to_source`, `verify_metric`, модели.
- Produces (`methodology.py`):
  - `CRITERIA: dict[Methodology, list[str]]` — дословно:
    - `R1`: скорость, качество, объективность, экономическая эффективность, персонализация;
    - `M1`: результат услуги, качество и надёжность, производительность и труд, опыт и доступность, доверие и распределение эффекта, реализуемость и масштаб;
    - `BUSINESS`: ROI, операционные затраты, время процесса, уровень ошибок.
  - `OTHER_CRITERION = "прочее"`.
  - `select_methodology(level: Level, sector: Sector) -> Methodology`: бизнес → `BUSINESS`; госсектор + `WORLD` → `M1`; госсектор + регионы РФ / Свердловская область → `R1`.
  - `infer_level(country: str, region: str|None) -> Level`: регион содержит «свердлов» (без учёта регистра) или «екатеринбург» → `SVERDLOVSK`; страна «Россия»/«РФ»/«Russia» → `RF_REGIONS`; иначе `WORLD`.
  - `methodology_prompt() -> str` — описание трёх методик с критериями и примерами индикаторов из `Вводные данные/md/Презентация Аналитика.md` (слайды 5–7).
- Produces (`extract.py`):
  - `SYSTEM_PROMPT: str`;
  - `extract_cases(article: Article, llm: LLMClient, registry: SourceRegistry, today: date, max_chars: int) -> list[Case]`.

Контракт ответа LLM (описывается в `SYSTEM_PROMPT`):

```json
{"cases": [{"country": "", "region": null, "municipality": null, "organization": null,
  "sector": "госсектор|бизнес", "industry": "", "ai_technology": "", "title": "", "summary": "",
  "stage": "в разработке|пилот|внедрён|масштабирование|неизвестно",
  "metrics": [{"name": "", "criterion": "", "before": null, "after": null, "change": null,
               "unit": null, "kind": "факт|план", "quote": "дословная цитата"}]}]}
```

Правила промпта:
- кейс — это только конкретное внедрение (кто, где, что сделано); общие новости, мнения и анонсы рынка → `"cases": []`;
- цифры брать только из текста, `quote` — дословный фрагмент, нет цифры → нет метрики;
- текст статьи обрезается до `max_chars`.

После ответа:
- нераспознанные `stage`/`kind`/`sector` → `UNKNOWN`/`FACT`/`GOV`;
- `criterion`, которого нет в `CRITERIA[methodology]`, → `OTHER_CRITERION`;
- `level = infer_level(...)`, `methodology = select_methodology(...)`;
- `sources = [registry.to_source(article)]`, `metric.source_url = normalize_url(article.url)`;
- `quote_verified = verify_metric(m, article.text)`;
- `id = uuid4().hex[:12]`, `first_seen = updated = today`.

Ответ без ключа `cases` или с неверной структурой → `LLMFormatError`.

- [ ] **Step 1: Написать падающие тесты.**

```python
ART = Article(url="https://gubernia74.ru/news/1?utm_source=x", domain="gubernia74.ru", title="Пробки",
              text="В Челябинской области ИИ анализирует дорожную обстановку. Время в пробках сократилось с 13 до 5 минут.")

def reply(**metric):
    return {"cases": [{"country": "Россия", "region": "Челябинская область", "sector": "госсектор",
        "industry": "транспорт", "ai_technology": "компьютерное зрение", "title": "т", "summary": "с",
        "stage": "внедрён", "metrics": [{"name": "время в пробках", "criterion": "скорость",
        "before": "13 мин", "after": "5 мин", "kind": "факт", "quote": "сократилось с 13 до 5 минут", **metric}]}]}

def test_extract_builds_verified_case(registry):
    [c] = extract_cases(ART, FakeLLM([reply()]), registry, date(2026, 11, 7), 12000)
    assert c.level == Level.RF_REGIONS and c.methodology == Methodology.R1
    assert c.metrics[0].quote_verified and c.metrics[0].source_url == "https://gubernia74.ru/news/1"
    assert c.flags == [Flag.CONFIRMATION_SKIPPED]

def test_invented_number_is_flagged(registry):
    [c] = extract_cases(ART, FakeLLM([reply(after="4 мин")]), registry, date(2026, 11, 7), 12000)
    assert Flag.QUOTE_NOT_FOUND in c.flags

def test_non_case_article_returns_empty(registry):
    assert extract_cases(ART, FakeLLM([{"cases": []}]), registry, date(2026, 11, 7), 12000) == []

def test_unknown_criterion_and_stage_are_coerced(registry):
    r = reply(criterion="удобство"); r["cases"][0]["stage"] = "запущен"
    [c] = extract_cases(ART, FakeLLM([r]), registry, date(2026, 11, 7), 12000)
    assert c.metrics[0].criterion == "прочее" and c.stage == Stage.UNKNOWN

def test_sverdlovsk_and_business_methodology():
    assert infer_level("Россия", "Свердловская обл.") == Level.SVERDLOVSK
    assert select_methodology(Level.WORLD, Sector.BUSINESS) == Methodology.BUSINESS
    assert select_methodology(Level.WORLD, Sector.GOV) == Methodology.M1
```

`registry` — фикстура в `conftest.py`, загружает `config/sources.yaml`.

- [ ] **Step 2: Запустить.** Ожидается FAIL. **Step 3: Реализовать оба модуля.** **Step 4: Запустить.** Ожидается PASS.
- [ ] **Step 5: Commit** `feat: методики оценки и извлечение кейсов через LLM`.

---

### Task 7: Поиск Tavily, запросы и настройки

**Files:**
- Create: `src/aidigest/search.py`, `src/aidigest/config.py`, `config/queries.yaml`, `config/settings.yaml`, `tests/test_search.py`, `tests/test_config.py`
- Modify: `tests/fakes.py` (добавить `FakeSearch`)

**Interfaces:**
- Consumes: `DiskCache`, `CreditBudget`, `BudgetExceeded`, `normalize_url`, `domain_of`, `Article`.
- Produces (`config.py`):
  - `Settings`, поля и значения в `settings.yaml`: `run_budget: 30`, `first_run_budget: 100`, `confirm_share: 0.4`, `freshness_days: 30`, `max_results: 5`, `article_max_chars: 12000`, `recheck_after_days: 28`, `max_rechecks: 2`, `confirm_max_results: 5`;
  - `load_settings(path: Path) -> Settings`;
  - `QuerySpec(level: Level, text: str, use_registry_domains: bool, language: str)`;
  - `load_queries(path: Path) -> list[QuerySpec]`.
- Produces (`search.py`):
  - `class SearchClient(Protocol): def search(self, query: str, *, pool: str, include_domains: list[str]|None = None, exclude_domains: list[str]|None = None, start_date: date|None = None, max_results: int = 5) -> list[Article]`;
  - `TavilySearch(api_key: str|None, cache: DiskCache, budget: CreditBudget, offline: bool = False, client: Any = None)`:
    - `client` по умолчанию — `tavily.TavilyClient(api_key)`;
    - вызов `client.search(query=..., search_depth="basic", topic="general", include_raw_content="text", max_results=..., include_domains=..., exclude_domains=..., start_date="YYYY-MM-DD")`;
    - перед реальным вызовом `budget.spend(pool, 1)`, при кеш-попадании кредиты не тратятся;
    - `offline` и промах кеша → `[]`;
    - `Article.text = raw_content or content`, `url = normalize_url(url)`, результаты с пустым текстом отбрасываются;
    - атрибут `.credits_spent`.
- Produces (`tests/fakes.py`): `FakeSearch(results: dict[str, list[Article]] | Callable, cost: float = 1, budget: CreditBudget | None = None)` — пишет журнал вызовов `.calls: list[dict]`; если задан `budget`, вызывает `budget.spend(pool, cost)`.

`queries.yaml`: 10–14 запросов на обычный запуск, по 3–5 на уровень, русские и английские. Каждый уровень — минимум один запрос с `use_registry_domains: true` и один открытый. Для Свердловской области — запросы с «Свердловская область» и «Екатеринбург».

- [ ] **Step 1: Написать падающие тесты.**

```python
class FakeTavily:
    def __init__(self): self.calls = []
    def search(self, **kw):
        self.calls.append(kw)
        return {"results": [{"url": "https://e1.ru/a?utm_source=t", "title": "T", "content": "c", "raw_content": "полный текст"},
                            {"url": "https://x.ru/empty", "title": "E", "content": "", "raw_content": None}]}

def test_search_spends_one_credit_and_caches(tmp_path):
    b = CreditBudget(10); t = FakeTavily()
    s = TavilySearch(None, DiskCache(tmp_path), b, client=t)
    [a] = s.search("ИИ Екатеринбург", pool="collect", start_date=date(2026, 10, 8))
    assert a.url == "https://e1.ru/a" and a.text == "полный текст" and a.domain == "e1.ru"
    s.search("ИИ Екатеринбург", pool="collect", start_date=date(2026, 10, 8))
    assert len(t.calls) == 1 and b.spent == 1
    assert t.calls[0]["search_depth"] == "basic" and t.calls[0]["start_date"] == "2026-10-08"

def test_search_raises_when_pool_empty(tmp_path):
    s = TavilySearch(None, DiskCache(tmp_path), CreditBudget(1), client=FakeTavily())
    with pytest.raises(BudgetExceeded): s.search("q", pool="collect")

def test_offline_miss_returns_empty_without_call(tmp_path):
    t = FakeTavily()
    assert TavilySearch(None, DiskCache(tmp_path), CreditBudget(10), offline=True, client=t).search("q", pool="collect") == []
    assert t.calls == []

def test_real_configs_load():
    s = load_settings(Path("config/settings.yaml")); q = load_queries(Path("config/queries.yaml"))
    assert s.first_run_budget == 100 and s.confirm_share == 0.4
    assert {x.level for x in q} == set(Level) and len(q) <= 14
```

- [ ] **Step 2: Запустить.** Ожидается FAIL. **Step 3: Реализовать и заполнить YAML.** **Step 4: Запустить.** Ожидается PASS.
- [ ] **Step 5: Commit** `feat: поиск Tavily с бюджетом и кешем, конфиги запросов`.

---

### Task 8: Подтверждение вторым источником

**Files:**
- Create: `src/aidigest/confirm.py`, `tests/test_confirm.py`

**Interfaces:**
- Consumes: `SearchClient`, `LLMClient`, `SourceRegistry`, `quote_in_text`, `normalize_url`, `Case.recompute_status`.
- Produces:
  - `plan_confirmation_queue(cases: list[Case], new_ids: set[str], today: date, recheck_after_days: int, max_rechecks: int) -> list[Case]`. В очередь попадают только кейсы с метриками, в порядке:
    1. новые (`id in new_ids`, `attempts == 0`);
    2. отложенные (`attempts == 0`, не новые);
    3. повтор (`status == SINGLE`, `1 <= attempts <= max_rechecks`, с последней попытки прошло `>= recheck_after_days` дней).

    Кейсы `CONFIRMED`/`CONFLICT` не повторяются.
  - `confirmation_query(case: Case) -> str` — через пробел: `region or country`, `organization`, `ai_technology`, `title` (пустые пропускаются).
  - `CONFIRM_SYSTEM_PROMPT: str`.
  - `confirm_case(case: Case, search: SearchClient, llm: LLMClient, registry: SourceRegistry, today: date, max_results: int) -> None`:
    - `search(confirmation_query(case), pool="confirm", exclude_domains=<домены источников кейса>, max_results=...)` — `BudgetExceeded` пробрасывается **до** изменения кейса;
    - затем `attempts += 1`, `last_confirmation_attempt = today`;
    - если статей нет → `recompute_status`, выход;
    - LLM получает метрики (с индексами) и тексты статей и отвечает `{"matches": [{"metric_index": 0, "url": "", "value": "", "agrees": true, "quote": ""}]}`;
    - совпадение принимается, только если `url` есть среди найденных статей и `quote_in_text(quote, text этой статьи)`;
    - `agrees` → `metrics[i].confirmed_by += [url]`, иначе `conflicting_values += [f"{value} ({url})"]`;
    - источник принятого совпадения добавляется в `case.sources` (без дублей по `normalize_url`);
    - в конце `recompute_status()`.

- [ ] **Step 1: Написать падающие тесты.**

```python
D = date(2026, 11, 7)
KP = Article(url="https://chel.kp.ru/1", domain="chel.kp.ru", title="", text="время в заторах сократилось в 2,5 раза, ДТП со 161 до 122")

def test_queue_order_and_recheck_rules(make_case, make_metric):
    m = [make_metric()]
    new = make_case(id="n", metrics=m); deferred = make_case(id="d", metrics=m)
    old = make_case(id="o", metrics=m, confirmation_attempts=1, last_confirmation_attempt=D - timedelta(days=30))
    fresh = make_case(id="f", metrics=m, confirmation_attempts=1, last_confirmation_attempt=D - timedelta(days=3))
    done = make_case(id="x", metrics=m, confirmation_attempts=3, last_confirmation_attempt=D - timedelta(days=90))
    nometrics = make_case(id="z", metrics=[])
    q = plan_confirmation_queue([old, deferred, new, fresh, done, nometrics], {"n"}, D, 28, 2)
    assert [c.id for c in q] == ["n", "d", "o"]

def test_confirm_agrees_adds_source(make_case, make_metric, registry):
    c = make_case(metrics=[make_metric(change="-24%", quote="...")])
    llm = FakeLLM([{"matches": [{"metric_index": 0, "url": KP.url, "value": "161 → 122", "agrees": True, "quote": "ДТП со 161 до 122"}]}])
    confirm_case(c, FakeSearch(lambda **kw: [KP]), llm, registry, D, 5)
    assert c.confirmation_status == ConfirmationStatus.CONFIRMED and c.confirmation_attempts == 1
    assert KP.url in c.metrics[0].confirmed_by and any(s.domain == "chel.kp.ru" for s in c.sources)

def test_confirm_ignores_quote_not_in_article(make_case, make_metric, registry):
    c = make_case(metrics=[make_metric()])
    llm = FakeLLM([{"matches": [{"metric_index": 0, "url": KP.url, "value": "x", "agrees": True, "quote": "выдумано"}]}])
    confirm_case(c, FakeSearch(lambda **kw: [KP]), llm, registry, D, 5)
    assert c.confirmation_status == ConfirmationStatus.SINGLE and Flag.SINGLE_SOURCE in c.flags

def test_budget_exceeded_leaves_case_untouched(make_case, make_metric, registry):
    c = make_case(metrics=[make_metric()])
    s = FakeSearch(lambda **kw: [KP], budget=CreditBudget(0))
    with pytest.raises(BudgetExceeded): confirm_case(c, s, FakeLLM([]), registry, D, 5)
    assert c.confirmation_attempts == 0 and Flag.CONFIRMATION_SKIPPED in c.flags
```

- [ ] **Step 2: Запустить.** Ожидается FAIL. **Step 3: Реализовать.** **Step 4: Запустить.** Ожидается PASS.
- [ ] **Step 5: Commit** `feat: подтверждение показателей вторым источником`.

---

### Task 9: Дедупликация, слияние, хранилище

**Files:**
- Create: `src/aidigest/dedup.py`, `src/aidigest/store.py`, `tests/test_dedup.py`, `tests/test_store.py`

**Interfaces:**
- Consumes: `LLMClient`, `normalize_text`, `normalize_url`, `extract_numbers`, модели.
- Produces (`dedup.py`):
  - `DEDUP_SYSTEM_PROMPT: str`.
  - `find_duplicate(case: Case, existing: list[Case], llm: LLMClient, max_candidates: int = 5) -> Case | None`:
    - кандидаты — тот же `level` и совпадающий нормализованный `region or country`;
    - среди них приоритет у пересечения слов (длиной ≥ 4) в `organization` + `ai_technology` + `title`;
    - пустой список кандидатов → `None` без вызова LLM;
    - LLM получает новый кейс и до `max_candidates` кандидатов и отвечает `{"duplicate_id": "<id>" | null}`;
    - `id`, которого нет среди кандидатов, считается `null`.
  - `merge_into(target: Case, new: Case, today: date) -> None`:
    - добавляет источники без дублей по `normalize_url`;
    - метрика нового кейса с тем же `criterion` и тем же набором чисел (`extract_numbers` от before/after/change), что у метрики `target`, из **другого домена** → её `source_url` добавляется в `confirmed_by` этой метрики;
    - иначе метрика добавляется как есть;
    - `stage` = более зрелая из двух (`UNKNOWN` — наименьшая);
    - `updated = today`, затем `recompute_status()`.
- Produces (`store.py`):
  - `StoreData(cases: list[Case] = [], processed_urls: set[str] = set())`;
  - `CaseStore(path: Path)`:
    - `.load() -> StoreData` — нет файла → пустой;
    - `.save(data: StoreData) -> None` — JSON UTF-8, `indent=2`, `ensure_ascii=False`, `processed_urls` отсортированы, запись через `path.with_suffix(".tmp")` + `os.replace`.

- [ ] **Step 1: Написать падающие тесты.**

```python
def test_no_candidates_no_llm_call(make_case):
    llm = FakeLLM([])
    assert find_duplicate(make_case(region="Татарстан"), [make_case(region="Белгородская область")], llm) is None
    assert llm.calls == 0

def test_llm_picks_duplicate(make_case):
    old = make_case(id="old", region="Белгородская область", ai_technology="цифровой двойник водоснабжения")
    new = make_case(region="Белгородская область", ai_technology="цифровой двойник")
    assert find_duplicate(new, [old], FakeLLM([{"duplicate_id": "old"}])).id == "old"
    assert find_duplicate(new, [old], FakeLLM([{"duplicate_id": "чужой"}])) is None

def test_merge_same_metric_other_domain_confirms(make_case, make_metric, make_source):
    t = make_case(stage=Stage.PILOT, metrics=[make_metric(criterion="качество", change="-23%", source_url="https://chr.rbc.ru/1")],
                  sources=[make_source("https://chr.rbc.ru/1")])
    n = make_case(stage=Stage.DEPLOYED, metrics=[make_metric(criterion="качество", change="23%", source_url="https://itrussia.media/2")],
                  sources=[make_source("https://itrussia.media/2")])
    merge_into(t, n, date(2026, 11, 7))
    assert t.metrics[0].confirmed_by == ["https://itrussia.media/2"] and len(t.metrics) == 1
    assert t.stage == Stage.DEPLOYED and len(t.sources) == 2
    assert t.confirmation_status == ConfirmationStatus.CONFIRMED

def test_store_roundtrip(tmp_path, make_case):
    st = CaseStore(tmp_path / "cases.json"); st.save(StoreData([make_case()], {"https://a.ru/1"}))
    d = st.load(); assert len(d.cases) == 1 and d.processed_urls == {"https://a.ru/1"}
    assert "регионы РФ" in (tmp_path / "cases.json").read_text(encoding="utf-8")

def test_failed_save_keeps_old_file(tmp_path, make_case, monkeypatch):
    p = tmp_path / "cases.json"; st = CaseStore(p); st.save(StoreData([make_case()], set()))
    before = p.read_text(encoding="utf-8")
    monkeypatch.setattr("aidigest.store.os.replace", lambda *a: (_ for _ in ()).throw(OSError("диск")))
    with pytest.raises(OSError): st.save(StoreData([], set()))
    assert p.read_text(encoding="utf-8") == before
```

`make_source(url)` — фикстура в `conftest.py`.

- [ ] **Step 2: Запустить.** Ожидается FAIL. **Step 3: Реализовать.** **Step 4: Запустить.** Ожидается PASS.
- [ ] **Step 5: Commit** `feat: дедупликация кейсов и атомарное хранилище`.

---

### Task 10: Выгрузка в Excel

**Files:**
- Create: `src/aidigest/export_excel.py`, `tests/test_export_excel.py`

**Interfaces:**
- Consumes: `Case`, `RunReport` (определяется в задаче 11, здесь нужен только как `Mapping[str, Any] | None` → лист пар «параметр — значение»).
- Produces: `export_xlsx(cases: list[Case], report: Mapping[str, Any] | None, path: Path) -> None`.

Листы и столбцы (заголовки дословно):
- **«Кейсы»**: Уровень, Страна, Регион, Организация, Сектор, Отрасль, Технология ИИ, Название, Суть, Стадия, Методика, Показатели, Статус подтверждения, Флаги, Источники, Впервые найден, Обновлён.
  - «Показатели» — по строке на метрику: `"{name}: {before} → {after} ({change}) [{criterion}, {kind}]"`, пустые части опускаются.
  - «Флаги» и «Источники» — через перевод строки; источник — `"{url} ({reliability})"`.
- **«Показатели»**: ID кейса, Название кейса, Показатель, Критерий, Было, Стало, Изменение, Единица, Вид, Цитата, Источник, Цитата проверена, Подтверждено источниками, Расхождения.
- **«Отчёт запуска»** — только если `report` не `None`.

Сортировка «Кейсов»: сначала с метриками; затем по статусу (подтверждено → противоречие → один_источник); затем по уровню в порядке `Level`. Закрепить первую строку, включить автофильтр, перенос текста.

- [ ] **Step 1: Написать падающие тесты.**

```python
def test_export_sheets_order_and_headers(tmp_path, make_case, make_metric):
    a = make_case(title="без цифр", metrics=[])
    b = make_case(title="подтверждён", metrics=[make_metric(confirmed_by=["https://x.ru"])]); b.recompute_status()
    p = tmp_path / "out.xlsx"; export_xlsx([a, b], {"Кредитов потрачено": 3}, p)
    wb = openpyxl.load_workbook(p)
    assert wb.sheetnames == ["Кейсы", "Показатели", "Отчёт запуска"]
    ws = wb["Кейсы"]; hdr = [c.value for c in ws[1]]
    assert hdr[0] == "Уровень" and "Флаги" in hdr
    assert ws.cell(2, hdr.index("Название") + 1).value == "подтверждён"
    assert wb["Показатели"].max_row == 2

def test_export_without_report(tmp_path, make_case):
    p = tmp_path / "o.xlsx"; export_xlsx([make_case()], None, p)
    assert openpyxl.load_workbook(p).sheetnames == ["Кейсы", "Показатели"]
```

- [ ] **Step 2: Запустить.** Ожидается FAIL. **Step 3: Реализовать.** **Step 4: Запустить.** Ожидается PASS.
- [ ] **Step 5: Commit** `feat: выгрузка кейсов в Excel`.

---

### Task 11: Пайплайн и CLI

**Files:**
- Create: `src/aidigest/pipeline.py`, `src/aidigest/cli.py`, `src/aidigest/__main__.py`, `tests/test_pipeline.py`, `data/cases.json` (пустая база `{"cases": [], "processed_urls": []}`)

**Interfaces:**
- Consumes: всё выше.
- Produces (`pipeline.py`):
  - `RunReport` (dataclass): `credits_spent: float`, `llm_calls: int`, `articles_processed: int`, `articles_rejected: int`, `articles_failed: int`, `cases_new: int`, `cases_updated: int`, `confirmations_done: int`, `confirmations_deferred: int`, `budget_exhausted: bool`, `flags: dict[str, int]`; метод `.as_rows() -> dict[str, Any]` с русскими подписями (для Excel).
  - `Deps` (dataclass): `search: SearchClient`, `llm: LLMClient`, `registry: SourceRegistry`, `store: CaseStore`, `queries: list[QuerySpec]`, `settings: Settings`, `budget: CreditBudget`.
  - `run_cycle(deps: Deps, levels: set[Level], today: date) -> RunReport`.

Алгоритм `run_cycle`:
1. Загрузить базу.
2. Для каждого `QuerySpec` нужных уровней вызвать `search(pool="collect", include_domains=registry.domains_for(level) if use_registry_domains else None, start_date=today - freshness_days, max_results=settings.max_results)`.
   - `BudgetExceeded` → `budget_exhausted=True`, сбор прекращается.
   - Прочая ошибка поиска → лог в stderr, следующий запрос.
3. Каждую статью, URL которой нет в `processed_urls` и не встречался в этом запуске, обработать через `extract_cases`.
   - `LLMFormatError` → `articles_failed += 1`, статья **не** помечается обработанной.
   - Пустой результат → `articles_rejected += 1`.
   - Каждый кейс → `find_duplicate`. Дубль → `merge_into` (`cases_updated`), иначе добавить (`cases_new`, id в `new_ids`).
   - URL → `processed_urls`, `store.save` после каждой статьи.
4. `budget.close_collection()`.
5. `plan_confirmation_queue` → `confirm_case` по очереди. `BudgetExceeded` → остаток очереди считается в `confirmations_deferred`.
6. `store.save`, заполнить отчёт (`credits_spent = budget.spent`, `llm_calls = llm.calls`, распределение флагов по всем кейсам базы).

Produces (`cli.py`): `main(argv: list[str] | None = None) -> int`, подкоманды:
- `run [--first-run] [--budget N] [--levels мир,регионы РФ,Свердловская область] [--days N] [--offline]`:
  - бюджет = `--budget`, иначе `first_run_budget` при `--first-run`, иначе `run_budget`;
  - после цикла выгрузка `data/out/cases_YYYY-MM-DD.xlsx`;
  - отчёт печатается в консоль.
- `export` — Excel из базы без поиска.
- `eval` — задача 12.

Креды читаются из корня проекта `litellm.env` / `tavily.env` через `load_env_file`; при `--offline` отсутствие файлов не ошибка. Кеш — `data/cache/`.

- [ ] **Step 1: Написать падающие тесты** (фейки, `tmp_path`-хранилище, реальный `registry`).

```python
A1 = Article(url="https://e1.ru/1", domain="e1.ru", title="", text="Время ожидания сократилось с 10 до 2 минут.")
A2 = Article(url="https://e1.ru/2", domain="e1.ru", title="", text="Общая новость без кейса.")

def deps(tmp_path, search, llm, budget, registry, queries):
    return Deps(search, llm, registry, CaseStore(tmp_path / "c.json"), queries, load_settings(Path("config/settings.yaml")), budget)

def test_cycle_collects_dedups_and_reports(tmp_path, registry, case_reply):
    b = CreditBudget(30); s = FakeSearch(lambda **kw: [A1, A2], budget=b)
    def route(system, user):
        if system == CONFIRM_SYSTEM_PROMPT: return {"matches": []}
        if "без кейса" in user: return {"cases": []}
        return case_reply(region="Свердловская область", quote="сократилось с 10 до 2 минут", before="10 мин", after="2 мин")
    llm = FakeLLM(route)
    q = [QuerySpec(level=Level.SVERDLOVSK, text="ИИ Екатеринбург", use_registry_domains=False, language="ru")]
    r = run_cycle(deps(tmp_path, s, llm, b, registry, q), set(Level), date(2026, 11, 7))
    assert r.articles_processed == 2 and r.articles_rejected == 1 and r.cases_new == 1
    data = CaseStore(tmp_path / "c.json").load()
    assert data.cases[0].level == Level.SVERDLOVSK and data.processed_urls == {A1.url, A2.url}
    r2 = run_cycle(deps(tmp_path, s, llm, b, registry, q), set(Level), date(2026, 11, 8))
    assert r2.articles_processed == 0 and r2.cases_new == 0

def test_budget_exhausted_mid_collection(tmp_path, registry, case_reply):
    b = CreditBudget(1, confirm_share=0.0); s = FakeSearch(lambda **kw: [A1], budget=b)
    q = [QuerySpec(level=Level.SVERDLOVSK, text=t, use_registry_domains=False, language="ru") for t in ("a", "b")]
    llm = FakeLLM(lambda system, user: case_reply(quote="сократилось с 10 до 2 минут", before="10 мин", after="2 мин"))
    r = run_cycle(deps(tmp_path, s, llm, b, registry, q), set(Level), date(2026, 11, 7))
    assert r.budget_exhausted and r.cases_new == 1 and r.confirmations_deferred == 1
    assert Flag.CONFIRMATION_SKIPPED in CaseStore(tmp_path / "c.json").load().cases[0].flags

def test_llm_format_error_skips_article_without_marking(tmp_path, registry):
    class Broken:
        calls = 0
        def complete_json(self, system, user): raise LLMFormatError("битый")
    b = CreditBudget(30); s = FakeSearch(lambda **kw: [A1], budget=b)
    q = [QuerySpec(level=Level.WORLD, text="x", use_registry_domains=False, language="en")]
    r = run_cycle(deps(tmp_path, s, Broken(), b, registry, q), set(Level), date(2026, 11, 7))
    assert r.articles_failed == 1 and CaseStore(tmp_path / "c.json").load().processed_urls == set()

def test_cli_export_offline(tmp_path, monkeypatch, make_case):
    CaseStore(tmp_path / "cases.json").save(StoreData([make_case()], set()))
    monkeypatch.setenv("AIDIGEST_DATA_DIR", str(tmp_path))
    assert main(["export"]) == 0
    assert list((tmp_path / "out").glob("cases_*.xlsx"))
```

- `case_reply(**overrides)` — фикстура в `conftest.py`: собирает ответ формата задачи 6. Переданные ключи `region` и `stage` подставляет в кейс, остальные — в его единственную метрику.
- CLI читает корень данных из переменной окружения `AIDIGEST_DATA_DIR` (по умолчанию `data/`). Внутри него: `cases.json`, `cache/`, `out/`.

- [ ] **Step 2: Запустить** `.venv/Scripts/python -m pytest tests/test_pipeline.py -v`. Ожидается FAIL.
- [ ] **Step 3: Реализовать `pipeline.py`, `cli.py`, `__main__.py`, пустой `data/cases.json`.**
- [ ] **Step 4: Запустить весь набор** `.venv/Scripts/python -m pytest -v`. Ожидается PASS всех тестов.
- [ ] **Step 5: Проверить офлайн-запуск без сети.** `.venv/Scripts/python -m aidigest run --offline --budget 0`. Ожидается код 0, отчёт с нулями, xlsx в `data/out/`.
- [ ] **Step 6: Commit** `feat: регулярный цикл и консольные команды`.

---

### Task 12: Эталон и первая отладка на реальной LLM

**Files:**
- Create: `eval/reference_cases.yaml`, `src/aidigest/fetch.py`, `src/aidigest/evaluate.py`, `tests/test_evaluate.py`
- Modify: `src/aidigest/cli.py` (подкоманда `eval`), `.gitignore` (не игнорировать `eval/texts/`)

**Interfaces:**
- Consumes: `extract_cases`, `extract_numbers`, `DiskCache`, `LLMClient`.
- Produces:
  - `fetch_text(url: str, cache: DiskCache, manual_dir: Path, ref_id: str, index: int) -> str`:
    - если есть `manual_dir / f"{ref_id}-{index}.txt"` — вернуть его;
    - иначе кеш `fetch`, иначе `requests.get(timeout=20, headers={"User-Agent": <обычный браузерный>})` + `trafilatura.extract`;
    - ошибка → `""` с сообщением в stderr.
  - `ReferenceCase(id: str, title: str, urls: list[str], expected: list[ExpectedFigure])`, `ExpectedFigure(label: str, numbers: list[float])`.
  - `EvalResult(found: list[tuple[str, str]], missing: list[tuple[str, str]], unverified_metrics: int, empty_texts: list[str])`.
  - `run_eval(refs: list[ReferenceCase], llm: LLMClient, registry: SourceRegistry, cache: DiskCache, manual_dir: Path, today: date) -> EvalResult`. Ожидаемая цифра считается найденной, если **все** её `numbers` встречаются в числах (`extract_numbers` от before/after/change) метрик с `quote_verified=True` из кейсов статей этого эталона.

- [ ] **Step 1: Найти точные URL эталонных статей** через WebSearch/браузер (**не Tavily**) — по описаниям из `Вводные данные/md/рос и рег.md`:
  - gubernia74.ru — пробки, 13 → 5 мин;
  - chel.kp.ru — ДТП, 161 → 122;
  - chr.rbc.ru — двойник водоснабжения Белгорода, −23%, >9 млн руб., >90%;
  - itrussia.media — >230 объектов, −23% ремонтов >8 ч;
  - нацпроекты.рф — «ГосПромпт», 426 госслужащих / 25 ведомств.

  Записать в `eval/reference_cases.yaml` четыре эталона: `chelyabinsk-traffic` (2 URL), `belgorod-water` (2 URL), `tatarstan-gosprompt` (1 URL). Ожидаемые числа:
  - `[13, 5]`, `[161, 122]`;
  - `[23]`, `[9000000]`, `[90]`, `[230]`, `[8]`;
  - `[426, 25]`.
- [ ] **Step 2: Написать падающий тест `run_eval`** на `FakeLLM` и ручных текстах в `tmp_path`: одна цифра найдена, одна пропущена, одна метрика с непроверенной цитатой → `len(found)==1`, `len(missing)==1`, `unverified_metrics==1`.
- [ ] **Step 3: Запустить.** Ожидается FAIL. **Step 4: Реализовать `fetch.py`, `evaluate.py`, подкоманду `eval`** (печатает найдено / не найдено / непроверенные / пустые тексты; код 0, если `missing` пуст). **Step 5: Запустить.** Ожидается PASS.
- [ ] **Step 6: Скачать тексты.** `.venv/Scripts/python -m aidigest eval --fetch-only` — только HTTP, без LLM и без Tavily. Для пустых текстов сохранить текст статьи вручную в `eval/texts/<id>-<n>.txt`.
- [ ] **Step 7: Первый реальный прогон LLM.** `.venv/Scripts/python -m aidigest eval`. Это первый реальный вызов LiteLLM, около 5 вызовов. Если не найдены цифры или есть непроверенные метрики — дорабатывать `SYSTEM_PROMPT` и правила `quotes.py`, пока все ожидаемые цифры не найдутся. Повторные прогоны с тем же промптом бесплатны (кеш); при каждой правке промпта — новые вызовы.
- [ ] **Step 8: Commit** `feat: эталонная проверка извлечения` (включая `eval/reference_cases.yaml` и `eval/texts/`).

---

### Task 13: Отладочный запуск и первый полный запуск

**Files:**
- Modify: `config/queries.yaml`, промпты — по результатам; `data/cases.json` (наполняется).

- [ ] **Step 1: Пробный запуск.** `.venv/Scripts/python -m aidigest run --budget 5 --levels "Свердловская область"`. Ожидается: потрачено ≤ 5 кредитов, отчёт без падений, xlsx создан.
- [ ] **Step 2: Просмотр результата.**
  - Открыть xlsx и проверить, что кейсы осмысленные, у метрик есть цитаты, флаги стоят там, где должны.
  - Записать замеченные проблемы и поправить запросы/промпты.
  - Повторный прогон на тех же данных — `run --offline`, он берёт данные из кеша.
- [ ] **Step 3: Первый полный запуск.** `.venv/Scripts/python -m aidigest run --first-run`. Ожидается: потрачено ≤ 100 кредитов, кейсы по всем трём уровням, отчёт запуска в xlsx.
- [ ] **Step 4: Итог для пользователя.** Сводка: сколько кейсов по уровням, сколько подтверждено, сколько кредитов осталось в месяце (≈ 1000 − потраченное в задачах 12–13), путь к xlsx.
- [ ] **Step 5: Commit** `data: первый запуск пайплайна` (`data/cases.json`, правки конфигов и промптов).
