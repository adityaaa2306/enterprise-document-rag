"""Phase 4 — deploy artifacts + worker graceful shutdown."""
from __future__ import annotations

from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]


def test_dockerfile_multistage_targets():
    text = (BACKEND / "Dockerfile").read_text(encoding="utf-8")
    assert "AS builder" in text
    assert "AS runtime" in text
    assert "AS api" in text
    assert "AS worker" in text
    assert "tini" in text


def test_compose_separates_api_and_worker():
    text = (BACKEND / "docker-compose.yml").read_text(encoding="utf-8")
    assert "api:" in text
    assert "worker:" in text
    assert "postgres:" in text
    assert "target: api" in text
    assert "target: worker" in text
    assert "stop_grace_period" in text
    assert "CHROMA_PERSIST_DIRECTORY" in text
    assert "chromadb/chroma" not in text


def test_render_blueprint_exists():
    path = BACKEND / "render.yaml"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "green-agentic-api" in text
    # Portfolio default: single web service + embedded worker (shared Chroma disk)
    assert "RUN_EMBEDDED_WORKER" in text
    assert "type: worker" not in text
    assert "green-agentic-chroma" not in text
    assert "healthCheckPath: /api/health" in text
    assert "docker-entrypoint-api.sh" in text
    assert "dockerBuildTarget: api" in text
    assert "CHROMA_PERSIST_DIRECTORY" in text
    assert "railway" not in text.lower()
    assert "JWT_SECRET_KEY" in text
    assert "SERVICE_ROLE" in text

    root_blueprint = BACKEND.parent / "render.yaml"
    assert root_blueprint.is_file()
    root_text = root_blueprint.read_text(encoding="utf-8")
    assert "rootDir: backend" in root_text
    assert "dockerBuildTarget: api" in root_text
    assert "RUN_EMBEDDED_WORKER" in root_text


def test_dockerfile_targets_set_service_role():
    text = (BACKEND / "Dockerfile").read_text(encoding="utf-8")
    assert "ENV SERVICE_ROLE=api" in text
    assert "ENV SERVICE_ROLE=worker" in text
    assert "AS api" in text
    assert "AS worker" in text


def test_railway_artifacts_removed():
    assert not (BACKEND / "railway.toml").exists()
    assert not (BACKEND / "railway.worker.toml").exists()
    assert not (BACKEND / "scripts" / "migrate_railway.sh").exists()


def test_entrypoint_scripts_exist_and_executable_bits_documented():
    api = BACKEND / "scripts" / "docker-entrypoint-api.sh"
    worker = BACKEND / "scripts" / "docker-entrypoint-worker.sh"
    assert api.is_file()
    assert worker.is_file()
    api_text = api.read_text(encoding="utf-8")
    worker_text = worker.read_text(encoding="utf-8")
    assert "uvicorn" in api_text
    assert "python -m src.worker" in worker_text
    assert "timeout-graceful-shutdown" in api_text
    # Free-tier: embedded worker is in-process via lifespan, not a second process
    api_code = "\n".join(
        ln for ln in api_text.splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    )
    assert "python -m src.worker" not in api_code


def test_worker_shutdown_flag(monkeypatch):
    from src.worker import loop as worker_loop

    worker_loop._shutdown.clear()
    assert worker_loop.is_shutdown_requested() is False
    worker_loop.request_shutdown("test")
    assert worker_loop.is_shutdown_requested() is True
    worker_loop._shutdown.clear()


def test_shutdown_grace_setting_present():
    from src.core.config import settings

    assert hasattr(settings, "WORKER_SHUTDOWN_GRACE_SEC")
    assert float(settings.WORKER_SHUTDOWN_GRACE_SEC) > 0
