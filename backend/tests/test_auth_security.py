"""Security hardening for authentication."""
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
    monkeypatch.setenv("AUTH_RETURN_REFRESH_IN_BODY", "true")
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15")
    monkeypatch.setenv("AUTH_LOGIN_RATE_LIMIT", "5")
    monkeypatch.setenv("AUTH_LOGIN_RATE_WINDOW_SEC", "900")

    from src.core.config import settings
    from src.api.auth_rate_limit import get_auth_rate_limiter

    monkeypatch.setattr(settings, "APP_ENV", "testing")
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "phase1-test-secret-key-32chars!!")
    monkeypatch.setattr(settings, "CORS_ALLOW_ALL", True)
    monkeypatch.setattr(settings, "AUTH_COOKIE_ENABLED", False)
    monkeypatch.setattr(settings, "AUTH_RETURN_REFRESH_IN_BODY", True)
    monkeypatch.setattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", 15)
    monkeypatch.setattr(settings, "AUTH_LOGIN_RATE_LIMIT", 5)
    monkeypatch.setattr(settings, "AUTH_LOGIN_RATE_WINDOW_SEC", 900.0)
    monkeypatch.setattr(settings, "BCRYPT_ROUNDS", 10)
    monkeypatch.setattr(settings, "AUTO_CREATE_SCHEMA", False)
    get_auth_rate_limiter().reset()

    from src.agents import models as agent_models

    monkeypatch.setattr(agent_models, "load_all_models", lambda: None)

    from src.api.main import app

    with TestClient(app) as c:
        yield c
    get_auth_rate_limiter().reset()


def _email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def test_password_hashed_with_bcrypt():
    from src.api import auth as auth_mod

    hashed = auth_mod.get_password_hash("SecurePass123")
    assert hashed.startswith("$2")
    assert "SecurePass123" not in hashed
    assert auth_mod.verify_password("SecurePass123", hashed)
    assert not auth_mod.verify_password("wrong-password", hashed)


def test_weak_password_rejected_on_register(client):
    r = client.post(
        "/auth/register",
        json={
            "email": _email("weak"),
            "password": "short",
            "full_name": "Weak",
        },
    )
    # Schema layer returns 422; legacy strength check returned 400.
    assert r.status_code in (400, 422)
    detail = r.json().get("detail")
    blob = detail if isinstance(detail, str) else str(detail)
    assert "password" in blob.lower()


def test_login_rate_limited(client):
    email = _email("rl")
    client.post(
        "/auth/register",
        json={"email": email, "password": "SecurePass123", "full_name": "RL"},
    )
    # Burn the per-IP login budget with wrong passwords
    last = None
    for _ in range(6):
        last = client.post(
            "/auth/login",
            json={"email": email, "password": "WrongPass999"},
        )
    assert last is not None
    assert last.status_code == 429
    assert last.headers.get("Retry-After")


def test_access_token_expires(client):
    from datetime import timedelta
    from src.api import auth as auth_mod

    email = _email("exp")
    client.post(
        "/auth/register",
        json={"email": email, "password": "SecurePass123", "full_name": "Exp"},
    )
    login = client.post("/auth/login", json={"email": email, "password": "SecurePass123"})
    assert login.status_code == 200
    uid = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    ).json()["id"]

    expired = auth_mod.create_access_token(
        {"sub": str(uid)},
        expires_delta=timedelta(seconds=-30),
    )
    bad = client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert bad.status_code == 401


def test_jwt_secret_never_in_auth_responses(client):
    email = _email("sec")
    client.post(
        "/auth/register",
        json={"email": email, "password": "SecurePass123", "full_name": "Sec"},
    )
    login = client.post("/auth/login", json={"email": email, "password": "SecurePass123"})
    body = login.json()
    blob = str(body).lower()
    assert "jwt_secret" not in blob
    assert "phase1-test-secret" not in blob
    assert "hashed_password" not in blob
    assert body.get("access_token")
    assert body.get("refresh_token")
    assert body.get("expires_in") == 15 * 60


def test_refresh_token_stored_peppered():
    from src.db import refresh_tokens as rt
    from src.core.config import settings

    raw = rt.generate_raw_token()
    h = rt.hash_token(raw)
    assert h != raw
    assert len(h) == 64
    # Pepper uses JWT secret — changing secret changes hash
    prev = settings.JWT_SECRET_KEY
    try:
        settings.JWT_SECRET_KEY = "different-secret-key-32chars-min!!"
        assert rt.hash_token(raw) != h
    finally:
        settings.JWT_SECRET_KEY = prev


def test_unknown_email_still_runs_dummy_verify():
    from src.api import auth as auth_mod

    assert auth_mod.verify_password_with_dummy("anything", None) is False
