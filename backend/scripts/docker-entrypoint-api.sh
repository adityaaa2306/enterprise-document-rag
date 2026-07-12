#!/usr/bin/env bash
# API container entrypoint: migrate (optional) → uvicorn.
#
# Portfolio / free-tier: set RUN_EMBEDDED_WORKER=true so FastAPI lifespan
# starts the durable worker as an in-process daemon thread (shared NIM +
# Chroma memory). Do NOT spawn a second `python -m src.worker` process —
# that doubles RAM and causes Render free-tier OOM / 502 during jobs.
#
# Dedicated Background Worker service: leave RUN_EMBEDDED_WORKER=false and
# run docker-entrypoint-worker.sh on a separate service (requires shared
# remote Chroma — not available with PersistentClient on separate disks).
set -euo pipefail
cd "${APP_HOME:-/app}"

export APP_ENV="${APP_ENV:-production}"
export VECTOR_DB_PATH="${VECTOR_DB_PATH:-/data/aux}"
export CHROMA_PERSIST_DIRECTORY="${CHROMA_PERSIST_DIRECTORY:-/data/chroma}"
export PORT="${PORT:-8000}"
export UVICORN_GRACEFUL_TIMEOUT="${UVICORN_GRACEFUL_TIMEOUT:-30}"
export RUN_MIGRATIONS_ON_STARTUP="${RUN_MIGRATIONS_ON_STARTUP:-true}"
export RUN_EMBEDDED_WORKER="${RUN_EMBEDDED_WORKER:-false}"

mkdir -p "${VECTOR_DB_PATH}" "${CHROMA_PERSIST_DIRECTORY}" temp_uploads \
  "${OBJECT_STORAGE_LOCAL_ROOT:-/data/object_store}"

if [[ "${RUN_MIGRATIONS_ON_STARTUP}" == "true" || "${RUN_MIGRATIONS_ON_STARTUP}" == "1" ]]; then
  echo "[api] Running alembic upgrade head..."
  python -m alembic upgrade head
fi

if [[ "${RUN_EMBEDDED_WORKER}" == "true" || "${RUN_EMBEDDED_WORKER}" == "1" ]]; then
  export WORKER_ID="${WORKER_ID:-embedded-api-1}"
  echo "[api] RUN_EMBEDDED_WORKER=true — worker starts in-process via FastAPI lifespan (WORKER_ID=${WORKER_ID})"
fi

echo "[api] Starting uvicorn on 0.0.0.0:${PORT} (graceful=${UVICORN_GRACEFUL_TIMEOUT}s)"
exec uvicorn src.api.main:app \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --proxy-headers \
  --forwarded-allow-ips='*' \
  --timeout-graceful-shutdown "${UVICORN_GRACEFUL_TIMEOUT}"
