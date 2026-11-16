#!/usr/bin/env bash
# Пересобирает requirements.lock в чистом окружении python:3.13-slim (Linux, как на сервере).
# Запуск из корня проекта: ./tools/lock_deps.sh
set -euo pipefail
cd "$(dirname "$0")/.."

# Для Docker Desktop нужен путь Windows к файлам, а пути внутри контейнера
# Git Bash должен передать без преобразования.
checkout_dir=$PWD
if [[ "$OSTYPE" == msys* ]]; then
  checkout_dir=$(pwd -W)
fi

lock_tmp=$(mktemp ./requirements.lock.XXXXXX)
trap 'rm -f -- "$lock_tmp"' EXIT

MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$checkout_dir/pyproject.toml:/tmp/lock-input/pyproject.toml:ro" \
  -v "$checkout_dir/src:/tmp/lock-input/src:ro" \
  -w /tmp python:3.13-slim sh -c '
  set -e
  mkdir /tmp/build
  cp -r /tmp/lock-input/pyproject.toml /tmp/lock-input/src /tmp/build/
  pip install --no-cache-dir --disable-pip-version-check --root-user-action=ignore -q "/tmp/build[api,dev]"
  pip freeze --disable-pip-version-check > /tmp/frozen
  grep -v -i "^aidigest" /tmp/frozen
' > "$lock_tmp"

chmod 0644 "$lock_tmp"
mv -f -- "$lock_tmp" requirements.lock
echo "requirements.lock обновлён: $(wc -l < requirements.lock) пакетов"
