#!/usr/bin/env bash
# API container entrypoint: migrate (optional) → uvicorn (+ optional embedded worker).
#
# Free-tier / portfolio mode: set RUN_EMBEDDED_WORKER=true to run
# `python -m src.worker` in the same container as the API (no paid
# Background Worker required). Prefer a separate worker service in production.
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

WORKER_PID=""

_shutdown() {
  echo "[api] Shutting down..."
  if [[ -n "${WORKER_PID}" ]] && kill -0 "${WORKER_PID}" 2>/dev/null; then
    kill -TERM "${WORKER_PID}" 2>/dev/null || true
  fi
  if [[ -n "${UVICORN_PID:-}" ]] && kill -0 "${UVICORN_PID}" 2>/dev/null; then
    kill -TERM "${UVICORN_PID}" 2>/dev/null || true
  fi
  wait || true
}

if [[ "${RUN_EMBEDDED_WORKER}" == "true" || "${RUN_EMBEDDED_WORKER}" == "1" ]]; then
  export WORKER_ID="${WORKER_ID:-embedded-api-1}"
  echo "[api] Starting embedded durable worker (WORKER_ID=${WORKER_ID})..."
  python -m src.worker &
  WORKER_PID=$!
  # Give the worker a moment to write its first heartbeat
  sleep 1
fi

echo "[api] Starting uvicorn on 0.0.0.0:${PORT} (graceful=${UVICORN_GRACEFUL_TIMEOUT}s)"

if [[ -n "${WORKER_PID}" ]]; then
  # Do not exec — keep this shell as PID 1 child under tini so we can stop both.
  trap _shutdown TERM INT
  uvicorn src.api.main:app \
    --host 0.0.0.0 \
    --port "${PORT}" \
    --proxy-headers \
    --forwarded-allow-ips='*' \
    --timeout-graceful-shutdown "${UVICORN_GRACEFUL_TIMEOUT}" &
  UVICORN_PID=$!
  # Exit if either process dies
  wait -n "${WORKER_PID}" "${UVICORN_PID}" || true
  _shutdown
  exit 1
fi

exec uvicorn src.api.main:app \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --proxy-headers \
  --forwarded-allow-ips='*' \
  --timeout-graceful-shutdown "${UVICORN_GRACEFUL_TIMEOUT}"
