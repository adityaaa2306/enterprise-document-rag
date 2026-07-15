"""Phase 1 — authentication, refresh rotation, ownership."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("JWT_SECRET_KEY", "phase1-test-secret-key-32chars!!")
    monkeypatch.setenv("CORS_ALLOW_ALL", "true")
    monkeypatch.setenv("AUTH_COOKIE_ENABLED", "false")
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    monkeypatch.setenv("PERSIST_JOBS_TO_DB", "true")
    monkeypatch.setenv("PERSIST_CONVERSATIONS_TO_DB", "true")

    from src.core.config import settings

    monkeypatch.setattr(settings, "APP_ENV", "testing")
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "phase1-test-secret-key-32chars!!")
    monkeypatch.setattr(settings, "CORS_ALLOW_ALL", True)
    monkeypatch.setattr(settings, "AUTH_COOKIE_ENABLED", False)
    monkeypatch.setattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", 30)
    monkeypatch.setattr(settings, "REFRESH_TOKEN_EXPIRE_DAYS", 14)
    monkeypatch.setattr(settings, "AUTO_CREATE_SCHEMA", False)

    from src.agents import models as agent_models

    monkeypatch.setattr(agent_models, "load_all_models", lambda: None)

    from src.api.main import app

    with TestClient(app) as c:
        yield c


def _email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def _register_login(client: TestClient, email: str | None = None, password: str = "SecurePass123"):
    email = email or _email("user")
    r = client.post(
        "/auth/register",
        json={"email": email, "password": password, "full_name": "Test User"},
    )
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("access_token")
    assert data.get("refresh_token")
    data["email"] = email
    return data


def test_business_endpoints_require_auth(client):
    assert client.get("/documents").status_code == 401
    assert client.get("/dashboard-stats").status_code == 401
    assert client.get("/job-status/fake").status_code == 401


def test_login_refresh_logout_rotation(client):
    tokens = _register_login(client)
    access = tokens["access_token"]
    refresh = tokens["refresh_token"]

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200
    assert me.json()["email"] == tokens["email"]

    refreshed = client.post("/auth/refresh", json={"refresh_token": refresh})
    assert refreshed.status_code == 200
    new = refreshed.json()
    assert new["access_token"]
    assert new["refresh_token"]
    assert new["refresh_token"] != refresh

    reuse = client.post("/auth/refresh", json={"refresh_token": refresh})
    assert reuse.status_code == 401

    out = client.post(
        "/auth/logout",
        headers={"Authorization": f"Bearer {new['access_token']}"},
        json={"refresh_token": new["refresh_token"]},
    )
    assert out.status_code == 200

    again = client.post("/auth/refresh", json={"refresh_token": new["refresh_token"]})
    assert again.status_code == 401


def test_ownership_isolation(client):
    a = _register_login(client)
    b = _register_login(client)

    from src.memory import storage
    from src.db import jobs as job_store

    doc_id = f"doc-owner-{uuid.uuid4().hex[:12]}"
    a_id = client.get("/auth/me", headers={"Authorization": f"Bearer {a['access_token']}"}).json()["id"]
    storage.ensure_document_owner(doc_id, int(a_id))
    job_store.upsert_job(
        doc_id,
        status="complete",
        progress=100,
        message="done",
        user_id=int(a_id),
        owner_type="user",
        owner_id=str(a_id),
    )

    ra = client.get("/documents", headers={"Authorization": f"Bearer {a['access_token']}"})
    assert ra.status_code == 200

    rb = client.get(
        f"/documents/{doc_id}/routing",
        headers={"Authorization": f"Bearer {b['access_token']}"},
    )
    assert rb.status_code in (403, 404)

    rb_job = client.get(
        f"/job-status/{doc_id}",
        headers={"Authorization": f"Bearer {b['access_token']}"},
    )
    assert rb_job.status_code in (403, 404)


def test_expired_access_token_rejected(client):
    from src.api import auth as auth_mod
    from datetime import timedelta

    tokens = _register_login(client)
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    uid = me.json()["id"]
    expired = auth_mod.create_access_token(
        {"sub": str(uid)},
        expires_delta=timedelta(seconds=-10),
    )
    bad = client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert bad.status_code == 401
