# Развёртывание aiDigest в песочнице проектного офиса

Инструкция описывает стенд `ai-project-office`. На нём проверили выкладку релиза `adae5a3`, вход через публичный HTTPS и запуск FastAPI с PostgreSQL 17.12. По документации passportGenerator с 22 ноября 2026 года на том же HTTPS-адресе работают паспорта проектов под `/passport/`. [Инструкция для отдельного сервера с Docker Compose](deploy.md) описывает другой способ выкладки.

## Как устроен стенд

| Что | Где и как работает |
| --- | --- |
| Песочница | Ubuntu 24.04, пользователь `nikita` с UID 24061. Доступ по SSH и SFTP с ключом. Парольный и root-вход, SSH-туннели отключены. В проверенной сессии отсутствуют `sudo` и команда `docker`. |
| Публичный HTTPS | Nginx на хосте принимает запросы и передаёт их на `127.0.0.1:18143` хоста. Docker направляет этот порт в песочницу. Caddy принимает запросы на порту песочницы 8080 и направляет их в aiDigest (`127.0.0.1:8081`) или паспорта (`127.0.0.1:8082`). Сертификат обновляет Certbot на хосте. |
| Веб-приложение | `appctl` запускает общий `~/app/start.sh`. Тот поднимает Caddy, aiDigest через `~/app/start.sh.before-passport` и паспорта через `~/passport-app/start.sh`. Uvicorn aiDigest отдаёт React, `/api` и `/healthz`. FastAPI запускает сборщик отдельным процессом при запуске сбора. |
| PostgreSQL | PostgreSQL 17 установлен в домашнем каталоге через micromamba. Кластер хранится в `~/data/postgres`. FastAPI и PostgreSQL работают от `nikita`, подключение идёт через Unix-сокет в `~/data/pgsocket` с аутентификацией `peer` на порту сокета 5432. Оба приложения используют базу `aidigest`. Таблицы и `alembic_version` aiDigest находятся в `public`, паспортов — в `passport_generator`. |
| Файлы | Релизы лежат в `~/app/releases/<коммит>`. Кеш и логи приложения хранятся в `~/data/aidigest`, журнал PostgreSQL — в `~/data/postgres.log`. `findmnt` показывает, что `/home/nikita` смонтирован из `/srv/projects/ai-project-office/home` на хосте. Сохранение этого каталога при пересоздании нужно согласовать с администратором перед пересозданием стенда. |
| Лимиты | 0,75 vCPU, 512 МиБ RAM, 4 ГиБ swap, 128 процессов и потоков, 40 ГиБ и 200 тыс. файловых объектов. PostgreSQL запускается с `shared_buffers=64MB` и `max_connections=20`. Работу сайта проверили. Пиковое потребление при живом сборе ещё предстоит измерить. |

Порт SSH, адрес SSH и публичный HTTPS-адрес берите из выданной администратором инструкции. В примерах замените `ПОРТ` и `ХОСТ` своими значениями. Если в команде подключения есть `-i`, используйте тот же ключ с `scp`. В PowerShell выполняются команды для локальных файлов. Команды Bash выполняются после подключения по SSH.

```powershell
ssh -p ПОРТ nikita@ХОСТ
```

## 1. Проверить общую базу

На действующем стенде выполните в SSH:

```bash
pg_bin="$HOME/.local/aidigest-pg/pg17/bin"
"$pg_bin/psql" -X -w -h "$HOME/data/pgsocket" -p 5432 -U "$(id -un)" -d aidigest \
  -v ON_ERROR_STOP=1 -c "SELECT current_database(), current_user, inet_server_addr() IS NULL AS unix_socket, to_regclass('public.alembic_version') AS aidigest, to_regclass('passport_generator.alembic_version') AS passport;"
```

Ожидаются база `aidigest`, роль `nikita`, `unix_socket = t` и обе таблицы версий. При расхождении выясните состояние базы до переключения релиза. Действующий кластер и схема паспортов уже подготовлены.

### Установить PostgreSQL на новой песочнице

Если PostgreSQL уже установлен и база отвечает, переходите к сборке релиза. На новом стенде проверьте, что доступна Python 3.12 или новее и модуль для установки `pip`. Для работающего стенда команда `appctl status` показывает PID. При необходимости права процесса можно сверить через `stat -c %U /proc/ПИД`.

```bash
python3 --version
python3 -m ensurepip --version
appctl status
findmnt -T "$HOME/app" -o TARGET,SOURCE,FSTYPE
```

Выполните в SSH. Пакет conda-forge содержит сервер, `initdb`, `pg_ctl` и клиентские программы. Установка идёт в домашний каталог. Основная версия совпадает с версией в Compose. Точный номер исправлений может меняться. [Пакет PostgreSQL](https://anaconda.org/conda-forge/postgresql) · [Документация micromamba](https://mamba.readthedocs.io/en/stable/installation/micromamba-installation.html)

```bash
(
  set -e
  case "$(uname -m)" in
    x86_64) platform=linux-64 ;;
    aarch64) platform=linux-aarch64 ;;
    *) echo "Неизвестная архитектура: $(uname -m)" >&2; exit 1 ;;
  esac

  pg_tools="$HOME/.local/aidigest-pg"
  mkdir -p "$pg_tools"
  curl -fsSL \
    "https://github.com/mamba-org/micromamba-releases/releases/latest/download/micromamba-$platform" \
    -o "$pg_tools/micromamba"
  chmod 700 "$pg_tools/micromamba"
  MAMBA_ROOT_PREFIX="$pg_tools/mamba" "$pg_tools/micromamba" create \
    --yes --prefix "$pg_tools/pg17" --override-channels -c conda-forge 'postgresql=17'
  "$pg_tools/pg17/bin/postgres" --version
  "$pg_tools/pg17/bin/pg_dump" --version
)
```

Инициализация и проверка подключения. Повторный запуск блока использует существующий кластер и базу. Опция `-h ''` отключает TCP-прослушивание PostgreSQL.

```bash
(
  set -e
  umask 077
  pg_bin="$HOME/.local/aidigest-pg/pg17/bin"
  pg_data="$HOME/data/postgres"
  pg_socket="$HOME/data/pgsocket"
  pg_user="$(id -un)"
  mkdir -p "$pg_socket"

  if [ ! -f "$pg_data/PG_VERSION" ]; then
    "$pg_bin/initdb" -D "$pg_data" -U "$pg_user" \
      --locale=C.UTF-8 --encoding=UTF8 \
      --auth-local=peer --auth-host=scram-sha-256
  fi
  if ! "$pg_bin/pg_ctl" -D "$pg_data" status >/dev/null; then
    "$pg_bin/pg_ctl" -D "$pg_data" -l "$HOME/data/postgres.log" -w \
      -o "-h '' -k '$pg_socket' -p 5432 -c shared_buffers=64MB -c max_connections=20" start
  fi

  db_exists=$("$pg_bin/psql" -X -h "$pg_socket" -p 5432 -U "$pg_user" -d postgres \
    -Atc "SELECT 1 FROM pg_database WHERE datname = 'aidigest'")
  if [ "$db_exists" != 1 ]; then
    "$pg_bin/createdb" -h "$pg_socket" -p 5432 -U "$pg_user" aidigest
  fi

  "$pg_bin/psql" -X -h "$pg_socket" -p 5432 -U "$pg_user" -d aidigest \
    -c "SELECT current_database(), current_user, inet_server_addr() IS NULL AS unix_socket, 1 AS ok;"
)
```

Ожидаются `aidigest`, `nikita`, `t` и `1`. При ошибке запуска проверьте `tail -n 40 "$HOME/data/postgres.log"`.

## 2. Собрать и передать релиз

**На своём компьютере**, в PowerShell из корня репозитория. Выберите коммит для выкладки и соберите в этом checkout его фронтенд. Для релиза нужны Node.js 22, Git и Python. Блок собирает архив из файлов выбранного коммита, добавляет готовый фронтенд и два файла запуска. Значения секретов и содержимое базы в архив не входят.

```powershell
$release = (git rev-parse --short=7 HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $release -notmatch '^[0-9a-f]{7,40}$') { throw "Не определён коммит" }
if (git status --porcelain -- frontend) { throw "Перед сборкой проверьте изменения во frontend" }
$bundle = Join-Path ([IO.Path]::GetTempPath()) "aidigest-$release.zip"

Push-Location .\frontend
try {
    npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw "Не удалось установить зависимости фронтенда" }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw "Фронтенд не собрался" }
} finally {
    Pop-Location
}

git archive --format=zip "--output=$bundle" HEAD src config eval alembic.ini pyproject.toml requirements.lock
if ($LASTEXITCODE -ne 0) { throw "Не удалось создать архив" }

@'
from pathlib import Path
from sys import argv
from zipfile import ZIP_DEFLATED, ZipFile

with ZipFile(argv[1], "a", ZIP_DEFLATED) as archive:
    for path in sorted(Path("frontend/dist").rglob("*")):
        if path.is_file():
            archive.write(path, path.as_posix())
    for name in ("start.sh", "sandbox_app.py"):
        content = (Path("deploy/sandbox") / name).read_bytes().replace(b"\r\n", b"\n")
        archive.writestr(f"deploy/sandbox/{name}", content)

with ZipFile(argv[1]) as archive:
    assert archive.testzip() is None
    assert "frontend/dist/index.html" in archive.namelist()
    assert not any(Path(name).name.endswith(".env") for name in archive.namelist())
'@ | python - $bundle
if ($LASTEXITCODE -ne 0) { throw "Архив не прошёл проверку" }
Get-Item -LiteralPath $bundle
```

Закройте текущую SSH-сессию перед копированием. Передайте архив из того же окна PowerShell, чтобы переменная `$bundle` была доступна:

```powershell
scp -P ПОРТ $bundle "nikita@ХОСТ:/home/nikita/"
```

После копирования снова подключитесь по SSH.

**В SSH** подставьте SHA, напечатанный в имени архива. При обновлении указывайте новый SHA. Распаковка и установка зависимостей проходят до переключения сайта.

```bash
release_id=SHA_ИЗ_ИМЕНИ_АРХИВА
release="$HOME/app/releases/$release_id"
mkdir -p "$HOME/app/releases" "$HOME/app/tmp" &&
  mkdir "$release" &&
  python3 -m zipfile -e "$HOME/aidigest-$release_id.zip" "$release" &&
  cd "$release" &&
  python3 -m venv .venv &&
  TMPDIR="$HOME/app/tmp" .venv/bin/python -m pip install -r requirements.lock
```

## 3. Настроить вход

Файл `secrets.env` лежит в каталоге релиза рядом с `src` и имеет права `0600`. При первой установке выполните блок в SSH. Он спрашивает пароль через терминал и генерирует постоянный ключ сессии. Пароль и ключ на экран не выводятся.

```bash
(
  set -e
  umask 077
  cd "$release"
  python3 - <<'PY'
from getpass import getpass
from pathlib import Path
from secrets import token_hex

path = Path("secrets.env")
if path.exists():
    raise SystemExit("secrets.env уже существует")
password = getpass("Пароль для сайта: ")
if not password or password != password.strip().strip('"').strip("'"):
    raise SystemExit("Введите непустой пароль без пробелов и кавычек по краям")
if password != getpass("Повторите пароль: "):
    raise SystemExit("Пароли не совпали")
with path.open("x", encoding="utf-8") as file:
    file.write(f"WEB_USERNAME=test\nWEB_PASSWORD={password}\nWEB_SECRET_KEY={token_hex(32)}\n")
PY
)
```

При обновлении скопируйте существующий `secrets.env` между каталогами релизов **на самом стенде**, чтобы сохранить пароль и ключ сессии. Найдите SHA активного релиза в строке `release=` скрипта `~/app/start.sh.before-passport`.

```bash
previous_release="$HOME/app/releases/SHA_АКТИВНОГО_РЕЛИЗА"
install -m 600 "$previous_release/secrets.env" "$release/secrets.env"
```

При выкладке `10bc172` на общий стенд настройки входа перенесены из `web.env` релиза `adae5a3`. В корневой `sandbox_app.py` активного релиза добавлена совместимость с перенесёнными `litellm.env` и `tavily.env`, если они были в старом релизе. Перед следующей выкладкой перенесите эти настройки в единый `secrets.env` на стенде либо сохраните совместимый загрузчик и соответствующие env-файлы в новом релизе.

Для смены логина отредактируйте `WEB_USERNAME` в файле нового релиза. Проверяйте вход после переключения.

## 4. Проверить и переключить приложение

На действующем стенде точка переключения aiDigest — `~/app/start.sh.before-passport`. Общий `~/app/start.sh` запускает оба приложения и Caddy. Дождитесь завершения сборов aiDigest и заданий паспортов. Остановка через `appctl` затронет оба сайта.

Подготовьте стартовый скрипт в той же SSH-сессии, где заданы `$release_id` и `$release`. Шлюз передаёт процессу aiDigest `PORT=8081`.

```bash
(
  set -e
  [[ $release_id =~ ^[0-9a-f]{7,40}$ ]]
  cd "$release"
  test -r secrets.env
  test -r frontend/dist/index.html
  install -m 600 deploy/sandbox/sandbox_app.py sandbox_app.py
  entry="$HOME/app/start.sh.before-passport"
  test -x "$entry"
  sed -e "s/__RELEASE__/$release_id/g" -e 's/--host 0\.0\.0\.0/--host 127.0.0.1/' \
    deploy/sandbox/start.sh > "$entry.next"
  grep -q -- '--host 127.0.0.1' "$entry.next"
  bash -n "$entry.next"
  chmod 700 "$entry.next"
)
```

Остановите веб-процессы командой `appctl stop` и сделайте [резервную копию](#резервная-копия). PostgreSQL должен оставаться доступен по сокету. После успешной копии переключите скрипт и запустите оба сайта. FastAPI применит миграции aiDigest при старте. При ошибке резервного копирования запустите прежний релиз через `appctl start`.

```bash
(
  set -e
  entry="$HOME/app/start.sh.before-passport"
  cp -p "$entry" "$HOME/app/start.sh.before-aidigest"
  mv -Tf "$entry.next" "$entry"
  appctl start
  appctl status
)
```

На новой песочнице без паспортов первый запуск использует подготовленный `deploy/sandbox/start.sh` с подстановкой SHA и исходным адресом прослушивания. Установите его с правами `0700` в `~/app/start.sh` после копирования `sandbox_app.py` в корень релиза и запустите `appctl start`. При добавлении паспортов настройку общего запуска выполняют по инструкции `docs/deploy-sandbox.md` репозитория passportGenerator.

Проверьте маршрутизацию через локальный Caddy на общем стенде:

```bash
curl --fail --silent --show-error --max-time 10 http://127.0.0.1:8080/healthz
curl --fail --silent --show-error --max-time 10 http://127.0.0.1:8080/passport/api/health
```

По публичному HTTPS проверьте те же пути. Ожидаются `ok` и `{"status":"ok"}`. Откройте оба интерфейса, проверьте вход, список кейсов и выгрузку Excel в aiDigest. Кнопку запуска сбора во время веб-проверки не нажимайте. При сбое после переключения переходите к [откату](#откат).

## 5. Загрузить демонстрационные данные

В каталоге [deploy/sandbox](../deploy/sandbox/) лежат три скрипта:

- [Первая подборка](../deploy/sandbox/seed_aidigest_demo.py) добавляет 5 кейсов.
- [Вторая подборка](../deploy/sandbox/seed_aidigest_demo_more.py) добавляет ещё 9 кейсов.
- [Обновление KPI](../deploy/sandbox/update_demo_kpi.py) добавляет к карточке ЕВРАЗ НТМК связь с KPI «Затраты организаций на внедрение и использование ИИ» и уточняет стадию как «пилот» по публикации об опытной эксплуатации.

Передайте файлы с локального компьютера. Если подборки уже загружены, повторный импорт пропустит записи с теми же идентификаторами. Обновление KPI выполняется после второй подборки.

```powershell
scp -P ПОРТ .\deploy\sandbox\seed_aidigest_demo.py .\deploy\sandbox\seed_aidigest_demo_more.py .\deploy\sandbox\update_demo_kpi.py "nikita@ХОСТ:/home/nikita/"
```

На стенде укажите SHA **активного** релиза и запустите:

```bash
(
  set -e
  cd "$HOME/app/releases/SHA_АКТИВНОГО_РЕЛИЗА"
  export DATABASE_URL="postgresql+psycopg://$(id -un)@/aidigest?host=$HOME/data/pgsocket"
  export PYTHONPATH=src
  .venv/bin/python "$HOME/seed_aidigest_demo.py"
  .venv/bin/python "$HOME/seed_aidigest_demo_more.py"
  .venv/bin/python "$HOME/update_demo_kpi.py"
)
```

Импорт проверяет записи по модели `Case` и пишет через штатный `PgCaseStore` с блокировкой. Обновите страницу «Кейсы». Всего в подборках 14 карточек и 27 показателей. Они видны при фильтрации по всем трём уровням. Фильтр «KPI Стратегии» ищет явные связи по пункту 28.1. Обычные показатели вроде сокращения времени доступны через «Тип эффекта». Для проверки KPI выберите пункт про затраты. Он должен вернуть карточку ЕВРАЗ НТМК. Перезапуск приложения и внешние API-вызовы для импорта не требуются.

## Внешние API и состояние живого сбора

- **LiteLLM.** Со стенда список моделей вернулся и содержал выбранную модель. Проверка списка подтверждает подключение к прокси. Генерация и полный сбор на стенде отдельно не проверялись. `secrets.env` находится в каталоге релиза и использует `LITELLM_API_KEY`, `LITELLM_BASE_URL` и необязательный `LITELLM_MODEL`. По умолчанию модель берётся из `config/settings.yaml`. Вносите секреты на стенде с правами `0600`. Для скрытого интерактивного ввода в Python-блоке с heredoc подходит `getpass()`. Вызов `input()` в таком блоке читает stdin со скриптом и завершается `EOFError`.
- **Tavily.** Запрос `GET /usage` локально вернул `200`, со стенда — `403` и с ключом, и без ключа. Региональное ограничение согласуется с [условиями Tavily, п. 17.1](https://www.tavily.com/terms). Не тратьте поисковые кредиты на диагностику: контрольный запрос ниже не использует токен. Если на другом стенде возникнет аналогичная проблема, статус запроса можно проверить средствами приложения в рантайме через `aidigest.usage.fetch_tavily_usage`. Функция возвращает `None` при ошибке сети, статусе, отличном от `200`, или неожиданном формате.
- **Yandex Search API.** Провайдер по умолчанию в актуальном master. При переходе с релиза на Tavily добавьте `YANDEX_SEARCH_API_KEY` и `YANDEX_SEARCH_FOLDER_ID` в `secrets.env` нового релиза на стенде. Сборщик перечитывает файл при каждом запуске, поэтому после правки активного файла перезапуск через `appctl` не требуется. Сообщение «Не заданы настройки доступа к поиску» означает, что сборщик не получил как минимум одну обязательную настройку выбранного провайдера. Доступ со стенда проверяйте отдельным запуском с согласованным бюджетом.

```bash
curl -sS --max-time 15 -D - -o /dev/null https://api.tavily.com/usage
```

### Проверить LiteLLM без генерации

Если для нового релиза нужен доступ к LiteLLM, используйте этот блок в SSH после установки зависимостей. Он добавит недостающие настройки LiteLLM в `secrets.env` и проверит `/models`. Адрес и модель в этом блоке тоже вводятся скрыто.

```bash
(
  set -e
  umask 077
  cd "$release"
  PYTHONPATH=src .venv/bin/python - <<'PY'
from getpass import getpass
from pathlib import Path

import openai

from aidigest.config import load_settings
from aidigest.creds import LITELLM_KEYS, load_creds

path = Path("secrets.env")
default_model = load_settings(Path("config/settings.yaml")).llm_model
creds = load_creds(path, LITELLM_KEYS)
if not creds.get("LITELLM_API_KEY") or not creds.get("LITELLM_BASE_URL"):
    key = creds.get("LITELLM_API_KEY") or getpass("LITELLM_API_KEY: ").strip()
    url = creds.get("LITELLM_BASE_URL") or getpass("LITELLM_BASE_URL: ").strip()
    if not key or not url:
        raise SystemExit("Для LiteLLM нужны ключ и адрес")
    model = creds.get("LITELLM_MODEL") or getpass(f"LITELLM_MODEL [Enter = {default_model}]: ").strip() or default_model
    with path.open("a", encoding="utf-8") as file:
        file.write(f"\nLITELLM_API_KEY={key}\nLITELLM_BASE_URL={url}\nLITELLM_MODEL={model}\n")

creds = load_creds(path, LITELLM_KEYS)
model = creds.get("LITELLM_MODEL") or default_model
if not creds.get("LITELLM_API_KEY") or not creds.get("LITELLM_BASE_URL"):
    raise SystemExit("Для LiteLLM нужны ключ и адрес")
try:
    with openai.OpenAI(api_key=creds["LITELLM_API_KEY"], base_url=creds["LITELLM_BASE_URL"],
                       timeout=15, max_retries=0) as client:
        available = {entry.id for entry in client.models.list()}
except openai.APIStatusError as exc:
    raise SystemExit(f"LiteLLM: HTTP {exc.status_code}")
except openai.APIConnectionError:
    raise SystemExit("LiteLLM: не удалось подключиться")
print("LiteLLM: модель доступна" if model in available else "LiteLLM: модели нет в /models")
PY
)
```

## Эксплуатация и диагностика

```bash
appctl status
appctl logs
appctl restart
```

`appctl stop`, `appctl start` и `appctl restart` управляют общим запуском Caddy и двух приложений. Перед запуском проверьте доступность PostgreSQL. Если кластер остановлен, его можно запустить командой `pg_ctl` из скрипта aiDigest, чтобы оба приложения получили доступ к базе при старте.

- Если публичный сайт отдаёт `502`, проверьте `appctl status` и `appctl logs`. Локальный HTTP-запрос к `127.0.0.1:8080/healthz` помогает отличить запуск приложения от маршрутизации на хосте. Для нестандартного `PORT` подставьте настроенное значение.
- Если API падает при запуске, проверьте PostgreSQL через `pg_ctl -D "$HOME/data/postgres" status` и журнал `~/data/postgres.log`. `pg_ctl` лежит в `~/.local/aidigest-pg/pg17/bin`. Для `peer` процесс приложения должен работать от того же пользователя ОС, для которого создана роль в PostgreSQL.
- Если страница входа открывается, но POST входа возвращает `403`, попросите администратора проверить передачу публичного `Host` через Nginx. FastAPI сравнивает его с `Origin` браузера. Для сессионной cookie на стенде используется HTTPS.
- Для измерения ресурсов при первом живом сборе проверьте `memory.current`, `memory.peak`, `memory.events`, `memory.swap.current`, `cpu.stat` и `pids.current` в `/sys/fs/cgroup`, если эти файлы видны в песочнице. Рост `oom_kill` или длительная работа через swap — повод запросить 1 ГиБ RAM и повторить проверку.

## Резервная копия

После остановки веб-процессов снимите дамп схемы `public` для отката aiDigest. Команда проверяет, что PostgreSQL может прочитать оглавление. Скачайте копию через `scp` с тем же портом. Для аварийного восстановления всего стенда нужен отдельный полный дамп базы и резервная копия файлов паспортов по инструкции passportGenerator.

```bash
(
  set -e
  umask 077
  pg_bin="$HOME/.local/aidigest-pg/pg17/bin"
  mkdir -p "$HOME/data/backups"
  dump="$(mktemp "$HOME/data/backups/aidigest-$(date +%F)-XXXXXX.dump")"
  "$pg_bin/pg_dump" -h "$HOME/data/pgsocket" -p 5432 -U "$(id -un)" --schema=public -Fc -f "$dump" aidigest
  "$pg_bin/pg_restore" --list "$dump" >/dev/null
  printf 'Резервная копия: %s\n' "$dump"
)
```

## Откат

При совместимой схеме БД остановите общий запуск и верните прежний скрипт aiDigest. Затем проверьте оба сайта по шагам из раздела переключения.

```bash
appctl stop &&
  install -m 700 "$HOME/app/start.sh.before-aidigest" "$HOME/app/start.sh.before-passport.next" &&
  mv -Tf "$HOME/app/start.sh.before-passport.next" "$HOME/app/start.sh.before-passport" &&
  appctl start &&
  appctl status
```

Сохраните предыдущий каталог релиза до проверки обновления. При несовместимой миграции оставьте веб-процессы остановленными и согласуйте с администратором восстановление схемы `public` из дампа aiDigest перед запуском. Полное восстановление общей базы затронет паспорта. Проверьте наличие обеих таблиц версий и оба маршрута после восстановления.
