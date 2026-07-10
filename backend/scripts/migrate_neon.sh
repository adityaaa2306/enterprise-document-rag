#!/usr/bin/env bash
# Neon Postgres: use the pooled or direct connection string from the Neon console.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "ERROR: Set DATABASE_URL to your Neon connection string" >&2
  exit 1
fi
echo "Neon migrate..."
python -m alembic upgrade head
