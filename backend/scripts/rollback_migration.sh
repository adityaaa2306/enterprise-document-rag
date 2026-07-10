#!/usr/bin/env bash
# Downgrade durable-runtime tables only (see alembic revision downgrade).
set -euo pipefail
cd "$(dirname "$0")/.."
echo "Rolling back one Alembic revision..."
python -m alembic downgrade -1
echo "Also set feature flags to legacy mode if needed:"
echo "  PERSIST_JOBS_TO_DB=false"
echo "  PERSIST_CONVERSATIONS_TO_DB=false"
echo "  PERSIST_ROUTING_EVENTS_TO_DB=false"
