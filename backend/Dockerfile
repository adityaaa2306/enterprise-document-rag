# syntax=docker/dockerfile:1
# Multi-stage image for Green Agentic API + durable worker (Render).
# Build targets: `api` | `worker` (same layers, different CMD).
#
# Render Web Service:        dockerBuildTarget = api  (REQUIRED — last stage is worker)
# Render Background Worker:  dockerBuildTarget = worker
#
# Portfolio default: run API target with RUN_EMBEDDED_WORKER=true (shared Chroma disk).
#
# Verify locally:
#   docker build --target api -t green-api .
#   docker build --target worker -t green-worker .
#   docker inspect --format '{{.Config.Env}}' green-api | findstr SERVICE_ROLE
#   docker inspect --format '{{.Config.Cmd}}' green-api

ARG PYTHON_VERSION=3.12

# -----------------------------------------------------------------------------
# Stage 1: build deps into a venv
# -----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        g++ \
        libpq-dev \
        curl \
        git \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv

# requirements first → better layer cache when only app code changes
COPY requirements.txt .

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip \
 && pip install -r requirements.txt

COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
COPY scripts ./scripts

# -----------------------------------------------------------------------------
# Stage 2: slim runtime (shared)
# -----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    APP_HOME=/app \
    APP_ENV=production \
    VECTOR_DB_PATH=/data/aux \
    CHROMA_PERSIST_DIRECTORY=/data/chroma \
    OBJECT_STORAGE_LOCAL_ROOT=/data/object_store \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
        tini \
        libmagic1 \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser \
    && mkdir -p /data/aux /data/chroma /data/object_store /app/temp_uploads \
    && chown -R appuser:appuser /data /app

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build/alembic.ini /app/alembic.ini
COPY --from=builder /build/alembic /app/alembic
COPY --from=builder /build/src /app/src
COPY --from=builder /build/scripts /app/scripts

RUN sed -i 's/\r$//' /app/scripts/*.sh \
 && chmod +x /app/scripts/docker-entrypoint-api.sh \
             /app/scripts/docker-entrypoint-worker.sh \
             /app/scripts/migrate_neon.sh \
             /app/scripts/migrate_render.sh

USER appuser

EXPOSE 8000

ENTRYPOINT ["/usr/bin/tini", "--"]

# -----------------------------------------------------------------------------
# API target (Render Web Service)
# -----------------------------------------------------------------------------
FROM runtime AS api
ENV SERVICE_ROLE=api
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT:-8000}/api/health" || exit 1
CMD ["/app/scripts/docker-entrypoint-api.sh"]

# -----------------------------------------------------------------------------
# Worker target (Render Background Worker)
# -----------------------------------------------------------------------------
FROM runtime AS worker
ENV SERVICE_ROLE=worker
HEALTHCHECK --interval=60s --timeout=10s --start-period=90s --retries=3 \
  CMD python -c "from sqlalchemy import text; from src.db.session import get_engine; c=get_engine().connect(); c.execute(text('SELECT 1')); c.close()"
CMD ["/app/scripts/docker-entrypoint-worker.sh"]
