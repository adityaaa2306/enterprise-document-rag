"""Secure deployment: HTTPS, secrets, DB TLS, security headers, audit logs."""
from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("JWT_SECRET_KEY", "secure-deploy-test-secret-key-32c")
    monkeypatch.setenv("CORS_ALLOW_ALL", "true")
    monkeypatch.setenv("FORCE_HTTPS", "false")

    from src.core.config import settings
    from src.agents import models as agent_models

    monkeypatch.setattr(settings, "APP_ENV", "testing")
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "secure-deploy-test-secret-key-32c")
    monkeypatch.setattr(settings, "CORS_ALLOW_ALL", True)
    monkeypatch.setattr(settings, "FORCE_HTTPS", False)
    monkeypatch.setattr(settings, "AUTO_CREATE_SCHEMA", False)
    monkeypatch.setattr(agent_models, "load_all_models", lambda: None)

    from src.api.main import app

    with TestClient(app) as c:
        yield c


def test_security_headers_present(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert "strict-origin" in (r.headers.get("Referrer-Policy") or "").lower()
    assert "frame-ancestors" in (r.headers.get("Content-Security-Policy") or "")


def test_https_redirect_when_forced(monkeypatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("JWT_SECRET_KEY", "secure-deploy-test-secret-key-32c")
    monkeypatch.setenv("FORCE_HTTPS", "true")
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")

    from src.core.config import settings
    from src.agents import models as agent_models

    monkeypatch.setattr(settings, "APP_ENV", "testing")
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "secure-deploy-test-secret-key-32c")
    monkeypatch.setattr(settings, "FORCE_HTTPS", True)
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
    monkeypatch.setattr(settings, "AUTO_CREATE_SCHEMA", False)
    monkeypatch.setattr(agent_models, "load_all_models", lambda: None)

    from src.api.main import app

    with TestClient(app, base_url="http://testserver") as c:
        # Plain HTTP without forwarded proto → redirect
        r = c.get("/documents", follow_redirects=False)
        assert r.status_code in (307, 308)
        # Proxied HTTPS
        r2 = c.get(
            "/api/health",
            headers={"X-Forwarded-Proto": "https"},
            follow_redirects=False,
        )
        assert r2.status_code == 200
        assert "strict-transport-security" in {k.lower() for k in r2.headers.keys()}


def test_database_url_rejects_ssl_disabled():
    from src.api.security_middleware import validate_database_url_for_public_exposure

    with pytest.raises(RuntimeError, match="sslmode=disable"):
        validate_database_url_for_public_exposure(
            "postgresql+psycopg://u:p@db.example.com:5432/app?sslmode=disable"
        )


def test_database_url_rejects_public_host_without_tls():
    from src.api.security_middleware import validate_database_url_for_public_exposure

    with pytest.raises(RuntimeError, match="TLS"):
        validate_database_url_for_public_exposure(
            "postgresql+psycopg://u:p@203.0.113.10:5432/app"
        )


def test_database_url_allows_private_and_neon_ssl():
    from src.api.security_middleware import validate_database_url_for_public_exposure

    validate_database_url_for_public_exposure(
        "postgresql+psycopg://green:green@postgres:5432/green_agentic"
    )
    validate_database_url_for_public_exposure(
        "postgresql+psycopg://u:p@ep-x.aws.neon.tech/neondb?sslmode=require"
    )


def test_placeholder_jwt_rejected_in_production():
    from src.core.config import Settings

    s = Settings(
        APP_ENV="production",
        JWT_SECRET_KEY="change-me-please-this-is-insecure!!!!",
        DATABASE_URL="postgresql+psycopg://u:p@ep-x.aws.neon.tech/db?sslmode=require",
        CORS_ORIGINS="https://app.example.com",
        CORS_ALLOW_ALL=False,
        NVIDIA_API_KEY="nvapi-test",
        OBJECT_STORAGE_BACKEND="local",
        DATABASE_REQUIRE_SSL=True,
        _env_file=None,
    )
    with pytest.raises(RuntimeError, match="placeholder"):
        s.validate_for_runtime(require_cors=False)


def test_auth_failure_emits_security_audit(client, caplog):
    from src.api.security_audit import reset_security_audit_state

    reset_security_audit_state()
    with caplog.at_level(logging.INFO, logger="security.audit"):
        r = client.post(
            "/auth/login",
            json={"email": "nobody@example.com", "password": "WrongPass999"},
        )
    assert r.status_code == 401
    joined = " ".join(rec.message for rec in caplog.records)
    assert "login_failure" in joined
    assert "WrongPass999" not in joined
