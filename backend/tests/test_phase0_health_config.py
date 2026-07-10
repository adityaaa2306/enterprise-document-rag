"""Phase 0 — health probes and config safety."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    # Avoid loading heavy models during import/lifespan for unit tests
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("CORS_ALLOW_ALL", "true")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-for-phase0")

    # Re-import settings after env patch is hard; patch methods on existing settings
    from src.core.config import settings

    monkeypatch.setattr(settings, "APP_ENV", "testing")
    monkeypatch.setattr(settings, "CORS_ALLOW_ALL", True)
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "test-secret-key-for-phase0")
    monkeypatch.setattr(settings, "AUTO_CREATE_SCHEMA", False)

    from src.agents import models as agent_models

    monkeypatch.setattr(agent_models, "load_all_models", lambda: None)

    from src.memory import storage

    monkeypatch.setattr(storage, "init_database", lambda **kwargs: None)

    from src.api.main import app

    with TestClient(app) as c:
        yield c


def test_api_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert body["env"] in ("testing", "development", "production")


def test_api_ready(client):
    r = client.get("/api/ready")
    # May be 200 or 503 depending on DB; structure must be present
    assert r.status_code in (200, 503)
    body = r.json()
    assert body["status"] in ("ready", "not_ready")
    assert "checks" in body
    assert "database" in body["checks"]
    assert "chroma" in body["checks"]
    assert "object_storage" in body["checks"]


def test_root_backwards_compatible(client):
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["health"] == "/api/health"


def test_jwt_secret_required_in_production():
    from src.core.config import Settings

    s = Settings(
        APP_ENV="production",
        JWT_SECRET_KEY="",
        CORS_ORIGINS="https://example.com",
        CORS_ALLOW_ALL=False,
        _env_file=None,
    )
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        s.resolved_jwt_secret()


def test_cors_allow_all_ignored_in_production():
    from src.core.config import Settings

    s = Settings(
        APP_ENV="production",
        JWT_SECRET_KEY="prod-secret",
        CORS_ORIGINS="https://app.example.com",
        CORS_ALLOW_ALL=True,
        _env_file=None,
    )
    assert s.cors_allow_origins() == ["https://app.example.com"]
    assert s.cors_allow_credentials() is True


def test_dev_jwt_fallback():
    from src.core.config import Settings

    s = Settings(
        APP_ENV="development",
        JWT_SECRET_KEY="",
        CORS_ALLOW_ALL=True,
        _env_file=None,
    )
    secret = s.resolved_jwt_secret()
    assert secret
    assert "dev-only" in secret


def test_cors_star_allowed_in_production_without_credentials():
    from src.core.config import Settings

    s = Settings(
        APP_ENV="production",
        JWT_SECRET_KEY="prod-secret-key-for-cors-star-test!!",
        CORS_ORIGINS="*",
        CORS_ALLOW_ALL=False,
        _env_file=None,
    )
    assert s.cors_allow_origins() == ["*"]
    assert s.cors_allow_credentials() is False
    s.validate_for_runtime(require_cors=True)


def test_worker_validation_skips_cors_but_requires_jwt():
    from src.core.config import Settings

    # Production worker without CORS_ORIGINS must still start if require_cors=False
    s = Settings(
        APP_ENV="production",
        JWT_SECRET_KEY="worker-prod-secret-key-32chars!!",
        CORS_ORIGINS="",
        CORS_ALLOW_ALL=False,
        _env_file=None,
    )
    s.validate_for_runtime(require_cors=False)

    # API path still requires CORS in production
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        s.validate_for_runtime(require_cors=True)

    # JWT still required for worker
    s2 = Settings(
        APP_ENV="production",
        JWT_SECRET_KEY="",
        CORS_ORIGINS="",
        _env_file=None,
    )
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        s2.validate_for_runtime(require_cors=False)
