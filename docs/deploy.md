# Выкладка aiDigest на сервер

Сервер — Linux (Ubuntu/Debian) с Docker. На нём работают два контейнера из одного образа:

- **web** — сайт для «Аналитики» (`python -m aidigest_web`), порт хоста `AIDIGEST_HTTP_PORT` (по умолчанию 80) → 8000 в контейнере;
- **worker** — сборщик (`python -m aidigest_web.worker`): берёт заявки, которые сайт пишет по кнопке «Запустить сбор», и выполняет их по одной.

Оба контейнера перезапускаются сами (`restart: unless-stopped`) и работают не от root, а от UID:GID из `.env` (по умолчанию 1000:1000). Данные лежат на хосте в `/srv/aidigest/data`, ключи — в `/srv/aidigest/secrets`. В образе нет ни данных, ни ключей.

> ⚠ **Предупреждение команде.** Коммит «база кейсов вне git» убирает `data/cases.json` и `data/credits.json` из репозитория. **Перед `git pull` этого коммита скопируйте оба файла** куда-нибудь вне проекта. У кого файлы не изменены, git удалит их из рабочей папки. После `pull` верните копии в `data/`: дальше они живут только локально и в git больше не попадают. Если у вас эти файлы **изменены локально**, `git pull` откажется проходить. Тогда:

> ```bash
> cp data/cases.json data/credits.json ~/aidigest-backup/   # копия вне репозитория (папку создайте заранее)
> git checkout -- data/cases.json data/credits.json         # вернуть файлы к версии из git
> git pull
> cp ~/aidigest-backup/cases.json ~/aidigest-backup/credits.json data/
> ```

---

## Первая установка

Все команды — на сервере, по SSH.

**1. Docker.** Поставить Docker Engine с плагином Compose **версии не ниже 2.24** (инструкция для Ubuntu/Debian — на docs.docker.com): `docker-compose.yml` использует длинную запись `env_file` с `required: false`, более старый Compose её не понимает. Версию показывает `docker compose version`. Выкладывать будет обычный пользователь, не root. Добавьте его в группу `docker` и перезайдите по SSH:

```bash
sudo usermod -aG docker "$USER"
docker compose version   # после перезахода работает без sudo
```

**2. Клон репозитория.**

- Если репозиторий публичный — по HTTPS:

  ```bash
  git clone https://github.com/LARCH1K/aiDigest.git ~/aiDigest
  ```

- Если приватный — по **read-only deploy key**. Ключ создаётся на сервере и живёт только в `~/.ssh` этого пользователя: в репозиторий и в образ он не попадает.

  ```bash
  ssh-keygen -t ed25519 -f ~/.ssh/aidigest_deploy -N "" -C "aidigest-server"
  cat ~/.ssh/aidigest_deploy.pub
  ```

  Открытый ключ (`.pub`) добавить в GitHub: репозиторий → Settings → Deploy keys → Add deploy key, **без** галочки «Allow write access». Затем:

  ```bash
  cat >> ~/.ssh/config <<'EOF'
  Host github-aidigest
      HostName github.com
      User git
      IdentityFile ~/.ssh/aidigest_deploy
      IdentitiesOnly yes
  EOF
  git clone git@github-aidigest:LARCH1K/aiDigest.git ~/aiDigest
  ```

Сервер выкладывает ветку `master`: `deploy.sh` делает `git pull` той ветки, что выбрана в клоне.

**3. Папки данных и ключей.** Папку данных нужно создать и отдать UID 1000 **до первого запуска**. Иначе Docker создаст её сам от root, и контейнеры (они работают не от root) не смогут в неё писать.

```bash
sudo mkdir -p /srv/aidigest/{data,secrets}
sudo chown -R 1000:1000 /srv/aidigest/data
sudo chown "$USER": /srv/aidigest/secrets
chmod 700 /srv/aidigest/secrets
```

Если у вас в `.env` другие `AIDIGEST_UID`/`AIDIGEST_GID`, в `chown` подставьте их.

**4. Ключи.** Три файла в `/srv/aidigest/secrets`. Формат — строки `КЛЮЧ=значение`. Файлы читает `docker compose` на хосте, поэтому их владелец — пользователь, который выкладывает. Значения ключей знают те, кто ведёт проект; в чат и в git их не пишут.

| Файл | Ключи | Кому передаётся |
|---|---|---|
| `web.env` | `WEB_PASSWORD`, `WEB_SECRET_KEY` | web |
| `tavily.env` | `TAVILY_TOKEN` | web (страница кредитов) и worker |
| `litellm.env` | `LITELLM_API_KEY`, `LITELLM_BASE_URL`, по желанию `LITELLM_MODEL` | worker |

```bash
cd /srv/aidigest/secrets
nano web.env      # и так же tavily.env, litellm.env
chmod 600 web.env tavily.env litellm.env
```

`WEB_PASSWORD` и `WEB_SECRET_KEY` обязательны: без них сайт откажется слушать `0.0.0.0` и контейнер web будет перезапускаться. `WEB_SECRET_KEY` — длинная случайная строка, например `openssl rand -hex 32`. Его не меняют между выкладками, иначе всех разлогинит.

**5. Настройки compose.**

```bash
cd ~/aiDigest
cp .env.example .env
```

В `.env` — папки данных и ключей, порт сайта и UID/GID контейнеров. Значения по умолчанию подходят для путей выше. Секретов в `.env` нет.

**6. Перенос базы.** Сервер становится главным источником базы. Текущие `cases.json` и `credits.json` переносятся один раз, с компьютера разработчика:

```bash
# на своём компьютере, из папки проекта
scp data/cases.json data/credits.json <пользователь>@<сервер>:~/
```

```bash
# на сервере
sudo install -o 1000 -g 1000 -m 644 ~/cases.json ~/credits.json /srv/aidigest/data/
rm ~/cases.json ~/credits.json
```

**7. Первая выкладка.**

```bash
cd ~/aiDigest
./deploy.sh
```

Сайт откроется по адресу `http://<IP-сервера>/`. Пока нет домена, сайт работает по HTTP без шифрования: пароль и cookie идут открытым текстом. Этот риск принят.

---

## Выкладка

Новая версия — это коммит в `master`. Чтобы выложить её, на сервере:

```bash
cd ~/aiDigest
./deploy.sh
```

Что печатает скрипт:

| Сообщение | Что значит |
|---|---|
| `==> git pull` | забирает новые коммиты (только fast-forward) |
| `git pull не прошёл — на сервере есть локальные изменения?` | в клоне на сервере кто-то правил файлы. Посмотреть `git status`, убрать правки (`git checkout -- <файл>`) и повторить. Код правят в репозитории, не на сервере |
| `==> Сборка образа` | `docker compose build`; если менялся только код, зависимости берутся из кеша |
| `==> Тесты в образе` | `pytest` в только что собранном образе, без сети и без ключей |
| `Тесты упали — контейнеры не тронуты.` | новая версия не выложена, работает старая. Исправить тесты в репозитории и выложить снова |
| `==> Перезапуск сайта` | web перезапущен на новой версии. Идущий сбор это не прерывает: сбор живёт в worker |
| `==> Идёт сбор, жду окончания (до 30 минут)` | worker сейчас собирает; скрипт ждёт и опрашивает его раз в 15 секунд |
| `Сайт обновлён, сборщик — нет: идёт сбор. Повторите ./deploy.sh позже или с --force.` | сбор не закончился за 30 минут. Сайт уже новый, worker — старый. Повторить позже |
| `==> Перезапуск сборщика` | worker перезапущен на новой версии |
| `==> Проверка сайта` | ждёт до 30 секунд, пока `/healthz` ответит `ok` |
| `Выложено: <коммит>` | всё готово |
| `Сайт не ответил на /healthz за 30 секунд: docker compose logs web` | web не поднялся; причина — в `docker compose logs web` (часто — нет `WEB_PASSWORD`/`WEB_SECRET_KEY`) |

**`./deploy.sh --force`** перезапускает worker сразу, даже если идёт сбор. Сбор оборвётся, на сайте он будет отмечен как прерванный, потраченные на него кредиты не вернутся. Нужен, только если сбор завис или срочно нужна новая версия сборщика.

Порт для проверки `/healthz` скрипт берёт так же, как compose: переменная окружения `AIDIGEST_HTTP_PORT`, затем `.env`, по умолчанию 80.

---

## Если сайт не работает или сбор упал

Причина неудачного сбора обычно видна на сайте: в карточке «Последний запуск» и в истории есть строка причины и ссылка на лог. Если сайт не открывается, то же самое можно прочитать на сервере:

```bash
cd ~/aiDigest
docker compose ps                     # оба ли контейнера запущены и healthy
docker compose logs --tail 100 web    # ошибки сайта (например, нет пароля)
docker compose logs --tail 100 worker # какие заявки взял сборщик и его ошибки
```

Итоги и логи запусков лежат в `/srv/aidigest/data/web/runs/` (хранятся последние 100 запусков). Имя файла — время запуска `ГГГГММДД-ЧЧММСС`:

- `<id>.json` — итог: `state`, `exit_code` и `reason` (причина одной фразой);
- `<id>.log` — полный вывод `python -m aidigest run`, причина — в строке `Причина: …`.

```bash
cd /srv/aidigest/data/web/runs
ls -t | head                          # последние запуски
cat <id>.json                         # итог и причина
grep '^Причина:' <id>.log; tail -n 50 <id>.log
```

Файлы принадлежат UID 1000. Если ваш пользователь на сервере — другой, читайте их через `sudo`.

Если сбор неожиданно отмечен как «оборвался», первым делом проверьте свободное место на диске: `df -h`. Когда диск заполнен, сборщик не может дописать лог и итог запуска, и сайт видит только остановившийся heartbeat.

---

## Как скачать копию базы себе

**Сервер — главный источник базы.** Новые кейсы появляются только там. Базу можно скачивать себе для анализа или отладки, но **обратно на сервер её не заливают**: так затрутся кейсы, собранные после скачивания.

```bash
# на своём компьютере, из папки проекта
scp <пользователь>@<сервер>:/srv/aidigest/data/cases.json data/cases.json
```

После каждого успешного сбора worker кладёт копию базы в `/srv/aidigest/data/backups/cases_ГГГГ-ММ-ДД_ЧЧММСС.json` (хранятся последние 30). Если база испортилась, нужную копию можно скачать или восстановить из неё на сервере:

```bash
ls /srv/aidigest/data/backups/
scp <пользователь>@<сервер>:/srv/aidigest/data/backups/cases_2026-11-08_120000.json ./
```

---

## Обновление зависимостей

Версии зависимостей закреплены в `requirements.lock`, и образ ставит их только оттуда. Список зависимостей по-прежнему задаёт `pyproject.toml`. После изменения `pyproject.toml` (или чтобы обновить версии) lock-файл пересобирают на своём компьютере, где есть Docker:

```bash
./tools/lock_deps.sh
```

Скрипт ставит проект с `[web,dev]` в чистом `python:3.13-slim` (Linux, как на сервере) и записывает `pip freeze` в `requirements.lock`. Затем проверить тесты, закоммитить `requirements.lock` вместе с `pyproject.toml` и выложить через `./deploy.sh`.

---

## Когда появится домен: HTTPS через Caddy

Код для этого менять не нужно. Меняется только `docker-compose.yml` в репозитории (правку коммитят в `master`, на сервере файлы не правят, иначе `git pull` перестанет проходить).

1. Добавить сервис `caddy` и `Caddyfile`, который проксирует домен на `web:8000`. Caddy сам получит сертификат Let's Encrypt; DNS-запись домена должна указывать на сервер, а порты 80 и 443 должны быть открыты.

   ```yaml
   services:
     caddy:
       image: caddy:2
       restart: unless-stopped
       ports:
         - "80:80"
         - "443:443"
       volumes:
         - ./Caddyfile:/etc/caddy/Caddyfile:ro
         - caddy_data:/data
         - caddy_config:/config
       depends_on:
         - web

   volumes:
     caddy_data:
     caddy_config:
   ```

   `Caddyfile`:

   ```
   aidigest.example.ru {
       reverse_proxy web:8000
   }
   ```

2. У сервиса `web` включить режим за прокси и **закрыть его порт наружу**:

   ```yaml
     web:
       environment:
         AIDIGEST_DATA_DIR: /data
         AIDIGEST_RUN_MODE: queue
         AIDIGEST_TRUST_PROXY: "1"
       ports:
         - "127.0.0.1:${AIDIGEST_HTTP_PORT:-8080}:8000"
   ```

   В `.env` на сервере поставить `AIDIGEST_HTTP_PORT=8080`: этот порт слушается только на `127.0.0.1`, и по нему `deploy.sh` проверяет `/healthz`. Порт 80 теперь занимает Caddy.

3. Выложить: `./deploy.sh`, затем один раз `docker compose up -d caddy` (`deploy.sh` перезапускает только web и worker).

Почему именно так:

- `AIDIGEST_TRUST_PROXY=1` включает учёт заголовков `X-Forwarded-*` и флаг `Secure` у cookie. Без него за HTTPS-прокси проверка `Origin` отвечает 403 (`https` против `http`). Кроме того, все посетители видны сайту с одного IP — адреса прокси. Ограничение входа считает неудачи по IP, поэтому 10 неверных паролей от кого угодно заблокируют вход **всем** на 10 минут.
- С `AIDIGEST_TRUST_PROXY=1` сайт верит заголовкам `X-Forwarded-*`. Поэтому web должен быть доступен **только через прокси**: не публиковать его порт наружу (только `127.0.0.1` или вообще без `ports`). Иначе любой, кто обратится к web напрямую, подделает свой IP в заголовке и обойдёт ограничение попыток входа.
