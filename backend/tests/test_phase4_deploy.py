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
    assert "green-agentic-worker" in text
    assert "green-agentic-chroma" not in text
    assert "healthCheckPath: /api/health" in text
    assert "docker-entrypoint-api.sh" in text
    assert "docker-entrypoint-worker.sh" in text
    assert "dockerBuildTarget: api" in text
    assert "dockerBuildTarget: worker" in text
    assert "CHROMA_PERSIST_DIRECTORY" in text
    assert "railway" not in text.lower()
    assert text.count("JWT_SECRET_KEY") >= 2
    assert "SERVICE_ROLE" in text


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
    assert "uvicorn" in api.read_text(encoding="utf-8")
    assert "python -m src.worker" in worker.read_text(encoding="utf-8")
    assert "timeout-graceful-shutdown" in api.read_text(encoding="utf-8")


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
