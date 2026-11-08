#!/usr/bin/env bash
# Пересобирает requirements.lock в чистом окружении python:3.13-slim (Linux, как на сервере).
# Запуск из корня проекта: ./tools/lock_deps.sh
set -euo pipefail
cd "$(dirname "$0")/.."

# MSYS_NO_PATHCONV — чтобы Git Bash на Windows не переписывал пути /src в C:/...
MSYS_NO_PATHCONV=1 docker run --rm -v "$PWD":/src -w /tmp python:3.13-slim sh -c '
  set -e
  mkdir /tmp/build
  cp -r /src/pyproject.toml /src/src /tmp/build/
  pip install --no-cache-dir --disable-pip-version-check --root-user-action=ignore -q "/tmp/build[web,dev]"
  pip freeze --disable-pip-version-check | grep -v -i "^aidigest" > /src/requirements.lock
'
echo "requirements.lock обновлён: $(wc -l < requirements.lock) пакетов"
