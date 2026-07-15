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
export ROUTING_TELEMETRY_PATH="${ROUTING_TELEMETRY_PATH:-/data/aux/routing_telemetry.jsonl}"
export PORT="${PORT:-8000}"
export UVICORN_GRACEFUL_TIMEOUT="${UVICORN_GRACEFUL_TIMEOUT:-30}"
export RUN_MIGRATIONS_ON_STARTUP="${RUN_MIGRATIONS_ON_STARTUP:-true}"
export RUN_EMBEDDED_WORKER="${RUN_EMBEDDED_WORKER:-false}"

mkdir -p "${VECTOR_DB_PATH}" "${CHROMA_PERSIST_DIRECTORY}" temp_uploads \
  "${OBJECT_STORAGE_LOCAL_ROOT:-/data/object_store}"

if [[ "${RUN_MIGRATIONS_ON_STARTUP}" == "true" || "${RUN_MIGRATIONS_ON_STARTUP}" == "1" ]]; then
  echo "[api] Running alembic upgrade head (240s timeout)..."
  # Neon cold starts can stall migrations past Render's port-scan window.
  # Prefer binding uvicorn over blocking forever on a stuck migrate.
  python - <<'PY'
import subprocess
import sys

try:
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        timeout=240,
    )
    raise SystemExit(completed.returncode)
except subprocess.TimeoutExpired:
    print("[api] alembic upgrade timed out after 240s — starting API; check /api/ready", flush=True)
    raise SystemExit(0)
PY
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
