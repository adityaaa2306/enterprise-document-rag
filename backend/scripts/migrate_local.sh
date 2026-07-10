#!/usr/bin/env bash
# Run Alembic migrations against DATABASE_URL (local SQLite or Postgres).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export DATABASE_URL="${DATABASE_URL:-sqlite:///./agentic_db.sqlite}"
echo "Migrating: $DATABASE_URL"
python -m alembic upgrade head
echo "Done."
