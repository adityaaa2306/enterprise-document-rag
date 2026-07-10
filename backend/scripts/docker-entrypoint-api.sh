#!/usr/bin/env bash
# API container entrypoint: migrate (optional) → uvicorn with graceful shutdown.
set -euo pipefail
cd "${APP_HOME:-/app}"

export APP_ENV="${APP_ENV:-production}"
export VECTOR_DB_PATH="${VECTOR_DB_PATH:-/data/chroma}"
export PORT="${PORT:-8000}"
export UVICORN_GRACEFUL_TIMEOUT="${UVICORN_GRACEFUL_TIMEOUT:-30}"
export RUN_MIGRATIONS_ON_STARTUP="${RUN_MIGRATIONS_ON_STARTUP:-true}"

mkdir -p "${VECTOR_DB_PATH}" temp_uploads \
  "${OBJECT_STORAGE_LOCAL_ROOT:-/data/object_store}"

if [[ "${RUN_MIGRATIONS_ON_STARTUP}" == "true" || "${RUN_MIGRATIONS_ON_STARTUP}" == "1" ]]; then
  echo "[api] Running alembic upgrade head..."
  python -m alembic upgrade head
fi

echo "[api] Starting uvicorn on 0.0.0.0:${PORT} (graceful=${UVICORN_GRACEFUL_TIMEOUT}s)"
exec uvicorn src.api.main:app \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --proxy-headers \
  --forwarded-allow-ips='*' \
  --timeout-graceful-shutdown "${UVICORN_GRACEFUL_TIMEOUT}"
