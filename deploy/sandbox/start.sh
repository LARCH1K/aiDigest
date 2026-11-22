#!/usr/bin/env bash
set -euo pipefail
umask 077

app_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
home_dir="$(dirname -- "$app_dir")"
release="$app_dir/releases/__RELEASE__"
pg_bin="$home_dir/.local/aidigest-pg/pg17/bin"
pg_data="$home_dir/data/postgres"
pg_socket="$home_dir/data/pgsocket"

cd "$release"
mkdir -p "$pg_socket"
if ! "$pg_bin/pg_ctl" -D "$pg_data" status >/dev/null; then
  "$pg_bin/pg_ctl" -D "$pg_data" -l "$home_dir/data/postgres.log" -w \
    -o "-h '' -k '$pg_socket' -p 5432 -c shared_buffers=64MB -c max_connections=20" start
fi

export DATABASE_URL="postgresql+psycopg://$(id -un)@/aidigest?host=$pg_socket"
export AIDIGEST_DATA_DIR="$home_dir/data/aidigest"
export PYTHONPATH="$release/src"
export TZ=Asia/Yekaterinburg

exec "$release/.venv/bin/python" -m uvicorn sandbox_app:create_application \
  --factory --host 0.0.0.0 --port "${PORT:-8080}" --no-proxy-headers
