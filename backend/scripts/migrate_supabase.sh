#!/usr/bin/env bash
# Supabase Postgres: set DATABASE_URL to the connection pooler or direct URI.
# Example:
#   export DATABASE_URL="postgresql://postgres.[ref]:[password]@aws-0-....pooler.supabase.com:6543/postgres"
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "ERROR: Set DATABASE_URL to your Supabase Postgres URI" >&2
  exit 1
fi
# Prefer psycopg; session.py normalizes postgresql:// → postgresql+psycopg://
echo "Supabase migrate..."
python -m alembic upgrade head
echo "Tip: keep Chroma on a persistent volume; do not use Supabase for embeddings in this phase."
