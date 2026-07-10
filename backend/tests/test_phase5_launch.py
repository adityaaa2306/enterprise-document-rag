"""Phase 5 — production launch kit (no live deploy required)."""
from __future__ import annotations

from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent


def test_phase5_docs_and_smoke_script_exist():
    assert (BACKEND / "docs" / "PHASE5_PRODUCTION_LAUNCH.md").is_file()
    assert (BACKEND / "scripts" / "smoke_production.py").is_file()
    assert (BACKEND / ".env.production.example").is_file()
    assert (ROOT / "frontend" / "vercel.json").is_file()
    text = (BACKEND / "docs" / "PHASE5_PRODUCTION_LAUNCH.md").read_text(encoding="utf-8")
    assert "Rollback" in text
    assert "Troubleshooting" in text
    assert "CORS_ORIGINS" in text


def test_request_logging_middleware_sets_header(monkeypatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("JWT_SECRET_KEY", "phase5-test-secret-key-32chars!!!")
    monkeypatch.setenv("CORS_ALLOW_ALL", "true")

    from src.core.config import settings
    from src.agents import models as agent_models

    monkeypatch.setattr(settings, "APP_ENV", "testing")
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "phase5-test-secret-key-32chars!!!")
    monkeypatch.setattr(settings, "CORS_ALLOW_ALL", True)
    monkeypatch.setattr(settings, "AUTO_CREATE_SCHEMA", False)
    monkeypatch.setattr(agent_models, "load_all_models", lambda: None)

    from fastapi.testclient import TestClient
    from src.api.main import app

    with TestClient(app) as client:
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.headers.get("x-request-id") or r.headers.get("X-Request-Id")
