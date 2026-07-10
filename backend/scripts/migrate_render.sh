#!/usr/bin/env bash
# Render release / pre-deploy: alembic upgrade head
# Set DATABASE_URL in the Render dashboard (Postgres).
set -euo pipefail
cd "$(dirname "$0")/.."
echo "Render migrate: ${DATABASE_URL:-unset}"
python -m alembic upgrade head
