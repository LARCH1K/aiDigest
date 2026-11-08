#!/usr/bin/env bash
# Выкладка aiDigest на сервере: обновить код, собрать образ, прогнать тесты,
# перезапустить сайт и (если не идёт сбор) сборщик.
# Запуск из папки проекта: ./deploy.sh [--force]
#   --force — перезапустить сборщик, даже если сейчас идёт сбор (сбор прервётся).
set -euo pipefail
cd "$(dirname "$0")"

FORCE=0
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    *) echo "Неизвестный параметр: $arg (допустимо: --force)" >&2; exit 2 ;;
  esac
done

# Порт сайта — как у docker compose: переменная окружения важнее .env, по умолчанию 80
HTTP_PORT=${AIDIGEST_HTTP_PORT:-}
if [ -z "$HTTP_PORT" ] && [ -f .env ]; then
  HTTP_PORT=$(grep -E '^AIDIGEST_HTTP_PORT=' .env | tail -n 1 | cut -d= -f2- | tr -d "\r\"'" || true)
fi
HTTP_PORT=${HTTP_PORT:-80}

echo "==> git pull"
if ! git pull --ff-only; then
  echo "git pull не прошёл — на сервере есть локальные изменения?" >&2
  exit 1
fi

echo "==> Сборка образа"
docker compose build

echo "==> Тесты в образе"
# Обычный docker run, а не compose run: в тесты не должны попасть секреты из env_file
if ! docker run --rm -e AIDIGEST_DATA_DIR=/tmp/t aidigest:latest python -m pytest -q -p no:cacheprovider; then
  echo "Тесты упали — контейнеры не тронуты." >&2
  exit 1
fi

echo "==> Перезапуск сайта"
docker compose up -d web

# Идёт ли сбор. Если worker не запущен, exec падает — значит, сбор не идёт.
worker_busy() {
  local out
  out=$(docker compose exec -T worker python -m aidigest_web.worker --status 2>/dev/null || true)
  [ "$out" = "busy" ]
}

if [ "$FORCE" -eq 0 ] && worker_busy; then
  echo "==> Идёт сбор, жду окончания (до 30 минут)"
  waited=0
  while worker_busy; do
    if [ "$waited" -ge 1800 ]; then
      echo "Сайт обновлён, сборщик — нет: идёт сбор. Повторите ./deploy.sh позже или с --force." >&2
      exit 1
    fi
    sleep 15
    waited=$((waited + 15))
  done
fi

echo "==> Перезапуск сборщика"
docker compose up -d worker

echo "==> Проверка сайта"
for _ in $(seq 1 30); do
  if curl -fsS "http://localhost:${HTTP_PORT}/healthz" >/dev/null 2>&1; then
    echo "Выложено: $(git rev-parse --short HEAD)"
    exit 0
  fi
  sleep 1
done
echo "Сайт не ответил на /healthz за 30 секунд: docker compose logs web" >&2
exit 1
