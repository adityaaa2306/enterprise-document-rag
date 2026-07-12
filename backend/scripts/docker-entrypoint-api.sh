#!/usr/bin/env bash
# API container entrypoint: migrate (optional) → uvicorn (+ optional embedded worker).
#
# Portfolio / free-tier mode: set RUN_EMBEDDED_WORKER=true to run
# `python -m src.worker` in the same container as the API (shared Chroma disk).
# Prefer a separate worker only when Chroma is a shared remote service.
#
# CRITICAL for Render:
# 1. Bind uvicorn as soon as migrations finish (PORT must open for deploy health).
# 2. Do NOT use `wait -n` — in non-interactive Docker shells it can return
#    immediately, which previously killed uvicorn before the port scan passed.
# 3. Start the embedded worker only after /api/health succeeds (or timeout).
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
UVICORN_PID=""
SHUTTING_DOWN=0

_shutdown() {
  if [[ "${SHUTTING_DOWN}" -eq 1 ]]; then
    return 0
  fi
  SHUTTING_DOWN=1
  echo "[api] Shutting down..."
  if [[ -n "${WORKER_PID}" ]] && kill -0 "${WORKER_PID}" 2>/dev/null; then
    kill -TERM "${WORKER_PID}" 2>/dev/null || true
  fi
  if [[ -n "${UVICORN_PID}" ]] && kill -0 "${UVICORN_PID}" 2>/dev/null; then
    kill -TERM "${UVICORN_PID}" 2>/dev/null || true
  fi
  wait || true
}

_wait_for_health() {
  local url="http://127.0.0.1:${PORT}/api/health"
  local i
  for i in $(seq 1 120); do
    if [[ -n "${UVICORN_PID}" ]] && ! kill -0 "${UVICORN_PID}" 2>/dev/null; then
      echo "[api] ERROR: uvicorn exited before becoming healthy (pid=${UVICORN_PID})"
      wait "${UVICORN_PID}" || true
      return 2
    fi
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "[api] Health check OK after ${i}s"
      return 0
    fi
    sleep 1
  done
  echo "[api] WARNING: /api/health not ready after 120s (continuing anyway)"
  return 1
}

_monitor_children() {
  # Poll until uvicorn or worker exits. Avoids unreliable `wait -n` under tini.
  while true; do
    if ! kill -0 "${UVICORN_PID}" 2>/dev/null; then
      echo "[api] uvicorn process exited — stopping container"
      wait "${UVICORN_PID}" 2>/dev/null || true
      return 1
    fi
    if [[ -n "${WORKER_PID}" ]] && ! kill -0 "${WORKER_PID}" 2>/dev/null; then
      echo "[api] embedded worker exited — stopping container"
      wait "${WORKER_PID}" 2>/dev/null || true
      return 1
    fi
    sleep 2
  done
}

echo "[api] Starting uvicorn on 0.0.0.0:${PORT} (graceful=${UVICORN_GRACEFUL_TIMEOUT}s)"

if [[ "${RUN_EMBEDDED_WORKER}" == "true" || "${RUN_EMBEDDED_WORKER}" == "1" ]]; then
  trap _shutdown TERM INT

  uvicorn src.api.main:app \
    --host 0.0.0.0 \
    --port "${PORT}" \
    --proxy-headers \
    --forwarded-allow-ips='*' \
    --timeout-graceful-shutdown "${UVICORN_GRACEFUL_TIMEOUT}" &
  UVICORN_PID=$!
  echo "[api] uvicorn pid=${UVICORN_PID}"

  # Render deploy health / port scan must succeed before loading the worker.
  health_rc=0
  _wait_for_health || health_rc=$?
  if [[ "${health_rc}" -eq 2 ]]; then
    _shutdown
    exit 1
  fi

  export WORKER_ID="${WORKER_ID:-embedded-api-1}"
  echo "[api] Starting embedded durable worker (WORKER_ID=${WORKER_ID})..."
  python -m src.worker &
  WORKER_PID=$!
  echo "[api] worker pid=${WORKER_PID}"

  _monitor_children || true
  _shutdown
  exit 1
fi

exec uvicorn src.api.main:app \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --proxy-headers \
  --forwarded-allow-ips='*' \
  --timeout-graceful-shutdown "${UVICORN_GRACEFUL_TIMEOUT}"
