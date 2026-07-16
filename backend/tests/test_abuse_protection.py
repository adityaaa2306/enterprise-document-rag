"""Abuse protection: API / AI / scrape rate limits and bot heuristics."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("JWT_SECRET_KEY", "abuse-test-secret-key-32chars!!!!")
    monkeypatch.setenv("CORS_ALLOW_ALL", "true")
    monkeypatch.setenv("FORCE_HTTPS", "false")
    monkeypatch.setenv("ABUSE_PROTECTION_ENABLED", "true")

    from src.core.config import settings
    from src.api.abuse_protection import get_abuse_limiter
    from src.agents import models as agent_models

    monkeypatch.setattr(settings, "APP_ENV", "testing")
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "abuse-test-secret-key-32chars!!!!")
    monkeypatch.setattr(settings, "CORS_ALLOW_ALL", True)
    monkeypatch.setattr(settings, "FORCE_HTTPS", False)
    monkeypatch.setattr(settings, "ABUSE_PROTECTION_ENABLED", True)
    monkeypatch.setattr(settings, "API_RATE_LIMIT", 8)
    monkeypatch.setattr(settings, "API_RATE_WINDOW_SEC", 60.0)
    monkeypatch.setattr(settings, "AI_RATE_LIMIT", 3)
    monkeypatch.setattr(settings, "AI_RATE_WINDOW_SEC", 60.0)
    monkeypatch.setattr(settings, "AI_RATE_LIMIT_GUEST", 2)
    monkeypatch.setattr(settings, "SCRAPE_RATE_LIMIT", 5)
    monkeypatch.setattr(settings, "SCRAPE_RATE_WINDOW_SEC", 60.0)
    monkeypatch.setattr(settings, "ABUSE_BOT_LIMIT_FACTOR", 0.25)
    monkeypatch.setattr(settings, "ABUSE_BLOCK_BOT_USER_AGENTS", True)
    monkeypatch.setattr(settings, "ABUSE_BLOCK_EMPTY_USER_AGENT", True)
    monkeypatch.setattr(settings, "AUTO_CREATE_SCHEMA", False)
    monkeypatch.setattr(agent_models, "load_all_models", lambda: None)
    get_abuse_limiter().reset()

    from src.api.main import app

    with TestClient(app) as c:
        yield c
    get_abuse_limiter().reset()


def test_classify_buckets():
    from src.api.abuse_protection import classify_request

    assert classify_request("/api/health", "GET") == "exempt"
    assert classify_request("/auth/login", "POST") == "auth"
    assert classify_request("/summarize", "POST") == "ai"
    assert classify_request("/rag-query", "POST") == "ai"
    assert classify_request("/chat", "POST") == "ai"
    assert classify_request("/documents", "GET") == "scrape"
    assert classify_request("/job-status/abc", "GET") == "scrape"
    assert classify_request("/auth/me", "GET") == "auth"


def test_health_exempt_from_limits(client):
    for _ in range(20):
        r = client.get("/api/health")
        assert r.status_code == 200


def test_api_rate_limit_returns_429(client):
    # /auth/me is auth bucket; use a scrape path that 401s but still counts.
    last = None
    for _ in range(10):
        last = client.get("/documents")
    assert last is not None
    assert last.status_code == 429
    assert last.headers.get("Retry-After")
    assert last.headers.get("X-RateLimit-Bucket") == "scrape"


def test_ai_rate_limit_tighter(client, monkeypatch):
    from src.core.config import settings
    from src.api.abuse_protection import get_abuse_limiter

    get_abuse_limiter().reset()
    monkeypatch.setattr(settings, "AI_RATE_LIMIT", 2)
    monkeypatch.setattr(settings, "AI_RATE_WINDOW_SEC", 60.0)

    last = None
    for _ in range(4):
        last = client.post(
            "/rag-query",
            json={"document_id": "x", "query": "hi"},
            headers={"User-Agent": "Mozilla/5.0 TestBrowser"},
        )
    assert last is not None
    assert last.status_code == 429
    assert last.headers.get("X-RateLimit-Bucket") == "ai"


def test_bot_user_agent_stricter_limit(client, monkeypatch):
    from src.core.config import settings
    from src.api.abuse_protection import get_abuse_limiter

    get_abuse_limiter().reset()
    monkeypatch.setattr(settings, "SCRAPE_RATE_LIMIT", 8)
    monkeypatch.setattr(settings, "ABUSE_BOT_LIMIT_FACTOR", 0.25)
    # Bot factor → limit 2
    last = None
    for _ in range(4):
        last = client.get(
            "/documents",
            headers={"User-Agent": "python-requests/2.31.0"},
        )
    assert last is not None
    assert last.status_code == 429


def test_login_still_rate_limited(client, monkeypatch):
    from src.core.config import settings
    from src.api.abuse_protection import get_abuse_limiter

    get_abuse_limiter().reset()
    monkeypatch.setattr(settings, "AUTH_LOGIN_RATE_LIMIT", 3)
    monkeypatch.setattr(settings, "AUTH_LOGIN_RATE_WINDOW_SEC", 900.0)
    monkeypatch.setattr(settings, "BCRYPT_ROUNDS", 10)

    last = None
    for _ in range(5):
        last = client.post(
            "/auth/login",
            json={"email": "rl@example.com", "password": "WrongPass999"},
            headers={"User-Agent": "Mozilla/5.0 TestBrowser"},
        )
    assert last is not None
    assert last.status_code == 429
