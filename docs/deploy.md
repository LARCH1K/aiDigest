# Развёртывание aiDigest

На сервере работают три контейнера Docker Compose. Nginx отдаёт интерфейс и направляет запросы API в FastAPI. PostgreSQL и API доступны внутри сети Compose. Сервер скачивает образы фронтенда и бэкенда из GitHub Packages, а образ PostgreSQL с Docker Hub.

## Первая установка

Понадобится Linux-сервер с Docker Engine и плагином Docker Compose. Установите их по инструкции Docker для [Ubuntu](https://docs.docker.com/engine/install/ubuntu/) или [Debian](https://docs.docker.com/engine/install/debian/). Команды ниже запускаются от пользователя с доступом к Docker.

В GitHub Actions откройте успешный прогон `CI`, запущенный push в `master` и завершивший задачу `publish`. Из сводки прогона возьмите полный SHA коммита для скачивания файлов и строку `AIDIGEST_VERSION=sha-…` для `.env`.

```bash
sudo install -d -o "$(id -u)" -g "$(id -g)" /srv/aidigest
cd /srv/aidigest
install -d -m 700 secrets
sudo install -d -o 1000 -g 1000 -m 750 data/backend
release_commit=FULL_COMMIT_SHA  # подставьте полный SHA из сводки
release_url="https://raw.githubusercontent.com/LARCH1K/aiDigest/$release_commit"
curl -fsSLO "$release_url/docker-compose.yml" &&
  curl -fsSLO "$release_url/.env.example" &&
  install -m 600 .env.example .env
```

Docker создаст каталог `data/postgres` при первой установке. Контейнер PostgreSQL сам назначит владельца. Если в `.env` настроены другие `AIDIGEST_UID` и `AIDIGEST_GID`, укажите те же числа в команде создания `data/backend`. Бэкенд пишет туда кеш и логи сборов.

В `.env` заполните `POSTGRES_PASSWORD` случайным значением из `openssl rand -hex 24` и укажите `AIDIGEST_VERSION` из сводки того же прогона. По умолчанию сайт доступен на порту 80. Порт меняется через `AIDIGEST_HTTP_PORT`.

Создайте в `/srv/aidigest/secrets` три файла с правами `0600`.

| Файл | Переменные |
| --- | --- |
| `web.env` | `WEB_USERNAME`, `WEB_PASSWORD`, `WEB_SECRET_KEY` |
| `tavily.env` | `TAVILY_TOKEN` |
| `litellm.env` | `LITELLM_API_KEY`, `LITELLM_BASE_URL`, опционально `LITELLM_MODEL` |

Для `WEB_SECRET_KEY` сгенерируйте отдельное значение через `openssl rand -hex 32` и сохраните его при обновлениях. Смена ключа завершит текущие сессии. Веб-интерфейс работает с пустой базой сразу после установки. Первый сбор запускается со страницы «Запуск».

Если пакеты приватные, создайте токен GitHub с правом `read:packages` и войдите в GHCR на сервере. Команда запросит токен как пароль.

```bash
docker login ghcr.io -u YOUR_GITHUB_USERNAME
```

## Выкладка и откат

В GitHub Actions откройте успешный прогон workflow `CI`, запущенный push в `master` и завершивший задачу `publish`. В сводке прогона скопируйте значение `AIDIGEST_VERSION=sha-1234567` в `.env`. Семь символов после `sha-` — первые семь символов SHA коммита этого прогона. Compose использует этот тег для обоих приложений. Если более новый прогон завершился ошибкой, используйте тег из предыдущего успешного прогона.

Из каталога `/srv/aidigest` выполните команды. К обновлению контейнеров переходите после успешной загрузки образов.

```bash
docker compose pull && docker compose up -d --no-build && docker compose ps
```

Откройте `http://IP_СЕРВЕРА` и войдите парой из `web.env`. При нестандартном порте добавьте его к адресу. Обновление бэкенда во время сбора прерывает запуск. Уже сохранённые кейсы останутся в базе, а запуск получит статус «прервано».

Для отката укажите в `.env` тег предыдущего успешного релиза и повторите выкладку. Если новая версия уже применила несовместимую миграцию, восстановите совместимую копию БД.

## Локальная сборка стека

Для сборки из исходников скопируйте `.env.example` в `.env` в корне репозитория. Задайте `AIDIGEST_VERSION=dev` и `POSTGRES_PASSWORD`, укажите локальные пути `AIDIGEST_DATA_HOST` и `AIDIGEST_SECRETS`. Создайте подкаталог `backend` в каталоге данных с правами записи для `AIDIGEST_UID:AIDIGEST_GID`.

```bash
docker compose up -d --build
```

## Резервные копии

Создавайте копии из каталога `/srv/aidigest`.

```bash
install -d -m 700 backups
backup=$(mktemp "backups/manual_$(date +%F_%H%M%S)_XXXXXX")
docker compose exec -T db pg_dump -U aidigest -Fc aidigest > "$backup" &&
  mv "$backup" "$backup.dump"
```

Скачайте нужный дамп командой `scp USER@SERVER:/srv/aidigest/backups/ИМЯ.dump .`. Храните локальную копию отдельно от серверной базы. Для ежедневной копии добавьте строку в crontab пользователя с доступом к Docker. Cron сохраняет новую копию только после успешного дампа.

```cron
30 3 * * * cd /srv/aidigest && f=backups/backup_$(date +\%F).dump && docker compose exec -T db pg_dump -U aidigest -Fc aidigest > "$f.tmp" && mv "$f.tmp" "$f" && find backups -type f -name 'backup_*.dump' -mtime +13 -delete
```

Восстановление пересоздаёт базу целиком. Сделайте свежую копию перед операцией. Подставьте имя нужного дампа и убедитесь, что он читается, прежде чем останавливать приложения.

```bash
dump=backups/backup_YYYY-MM-DD.dump
docker compose exec -T db pg_restore --list < "$dump" &&
docker compose stop frontend backend &&
docker compose exec -T db pg_restore -U aidigest -d postgres --clean --if-exists --create --exit-on-error < "$dump" &&
docker compose up -d --no-build
```

## Диагностика

```bash
docker compose ps
docker compose logs --tail=100 frontend backend db
docker compose exec -T backend python -c "from urllib.request import urlopen; print(urlopen('http://127.0.0.1:8000/healthz', timeout=5).read().decode())"
```

Чтобы проверить nginx, откройте `/healthz` на настроенном внешнем порту. При проблемах со сбором проверьте причину и лог на странице «Запуск». При ошибке записи из бэкенда проверьте владельца `data/backend`, при ошибке доступа в GHCR проверьте авторизацию и наличие тега.

Для HTTPS можно поставить Caddy перед фронтендом. Включите `AIDIGEST_SECURE_COOKIE=1`, ограничьте прямой доступ к порту фронтенда и настройте передачу клиентского IP от доверенного Caddy в nginx, чтобы сохранить отдельный лимит входа для каждого клиента.
