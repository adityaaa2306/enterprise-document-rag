#!/usr/bin/env bash
# Worker container entrypoint: durable job consumer with SIGTERM via tini.
set -euo pipefail
cd "${APP_HOME:-/app}"

export APP_ENV="${APP_ENV:-production}"
export VECTOR_DB_PATH="${VECTOR_DB_PATH:-/data/aux}"
export CHROMA_PERSIST_DIRECTORY="${CHROMA_PERSIST_DIRECTORY:-/data/chroma}"
export RUN_MIGRATIONS_ON_STARTUP="${RUN_MIGRATIONS_ON_STARTUP:-false}"

mkdir -p "${VECTOR_DB_PATH}" "${CHROMA_PERSIST_DIRECTORY}" temp_uploads \
  "${OBJECT_STORAGE_LOCAL_ROOT:-/data/object_store}"

# Worker does not own schema by default (API migrates). Opt-in for solo debugging.
if [[ "${RUN_MIGRATIONS_ON_STARTUP}" == "true" || "${RUN_MIGRATIONS_ON_STARTUP}" == "1" ]]; then
  echo "[worker] Running alembic upgrade head..."
  python -m alembic upgrade head
fi

echo "[worker] Starting durable worker (WORKER_ID=${WORKER_ID:-auto})"
exec python -m src.worker
