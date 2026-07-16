"""IDOR / ownership enforcement regression tests."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("JWT_SECRET_KEY", "idor-test-secret-key-32chars!!!!")
    monkeypatch.setenv("CORS_ALLOW_ALL", "true")
    monkeypatch.setenv("AUTH_COOKIE_ENABLED", "false")
    monkeypatch.setenv("PERSIST_JOBS_TO_DB", "true")
    monkeypatch.setenv("PERSIST_CONVERSATIONS_TO_DB", "true")

    from src.core.config import settings
    from src.api.auth_rate_limit import get_auth_rate_limiter

    monkeypatch.setattr(settings, "APP_ENV", "testing")
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "idor-test-secret-key-32chars!!!!")
    monkeypatch.setattr(settings, "CORS_ALLOW_ALL", True)
    monkeypatch.setattr(settings, "AUTH_COOKIE_ENABLED", False)
    monkeypatch.setattr(settings, "AUTO_CREATE_SCHEMA", False)
    monkeypatch.setattr(settings, "BCRYPT_ROUNDS", 10)
    get_auth_rate_limiter().reset()

    from src.agents import models as agent_models

    monkeypatch.setattr(agent_models, "load_all_models", lambda: None)

    from src.api.main import app

    with TestClient(app) as c:
        yield c
    get_auth_rate_limiter().reset()


def _email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def _register_login(client: TestClient, email: str | None = None):
    email = email or _email("user")
    password = "SecurePass123"
    r = client.post(
        "/auth/register",
        json={"email": email, "password": password, "full_name": "IDOR User"},
    )
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    data = r.json()
    data["email"] = email
    return data


def test_job_status_idor_blocked(client):
    a = _register_login(client)
    b = _register_login(client)
    from src.memory import storage
    from src.db import jobs as job_store

    job_id = str(uuid.uuid4())
    a_id = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {a['access_token']}"}
    ).json()["id"]
    storage.ensure_document_owner(job_id, int(a_id))
    job_store.upsert_job(
        job_id,
        status="complete",
        progress=100,
        message="done",
        user_id=int(a_id),
        owner_type="user",
        owner_id=str(a_id),
    )

    ok = client.get(
        f"/job-status/{job_id}",
        headers={"Authorization": f"Bearer {a['access_token']}"},
    )
    assert ok.status_code == 200

    denied = client.get(
        f"/job-status/{job_id}",
        headers={"Authorization": f"Bearer {b['access_token']}"},
    )
    assert denied.status_code in (403, 404)

    # Non-UUID path ids are rejected at the validation layer (422).
    garbage = client.get(
        "/job-status/not-a-uuid",
        headers={"Authorization": f"Bearer {b['access_token']}"},
    )
    assert garbage.status_code == 422

    cancel = client.post(
        f"/jobs/{job_id}/cancel",
        headers={"Authorization": f"Bearer {b['access_token']}"},
    )
    assert cancel.status_code in (403, 404)

    result = client.get(
        f"/job-result/{job_id}",
        headers={"Authorization": f"Bearer {b['access_token']}"},
    )
    assert result.status_code in (403, 404)


def test_conversation_assert_blocks_other_owner(client):
    from src.api.deps import assert_conversation_owner_for
    from src.db import conversations as conv_db
    from fastapi import HTTPException

    a = _register_login(client)
    b = _register_login(client)
    a_id = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {a['access_token']}"}
    ).json()["id"]
    b_id = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {b['access_token']}"}
    ).json()["id"]

    from src.memory import storage
    from src.db import jobs as job_store

    doc_id = f"doc-conv-{uuid.uuid4().hex[:12]}"
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

    cid = f"conv-{uuid.uuid4().hex[:12]}"
    assert conv_db.save_conversation_state(
        cid,
        doc_id,
        [{"role": "user", "content": "hi", "entities": [], "meta": {}}],
        owner_type="user",
        owner_id=str(a_id),
        user_id=int(a_id),
    )

    owner_a = {"owner_type": "user", "owner_id": str(a_id), "id": a_id}
    owner_b = {"owner_type": "user", "owner_id": str(b_id), "id": b_id}
    assert_conversation_owner_for(owner_a, cid, doc_id)
    with pytest.raises(HTTPException) as ei:
        assert_conversation_owner_for(owner_b, cid, doc_id)
    assert ei.value.status_code == 403


def test_conversation_save_cannot_reassign_owner():
    from src.db import conversations as conv_db

    cid = f"conv-reassign-{uuid.uuid4().hex[:12]}"
    doc = f"doc-{uuid.uuid4().hex[:8]}"
    assert conv_db.save_conversation_state(
        cid,
        doc,
        [{"role": "user", "content": "a", "entities": [], "meta": {}}],
        owner_type="user",
        owner_id="1",
        user_id=1,
    )
    with pytest.raises(PermissionError):
        conv_db.save_conversation_state(
            cid,
            doc,
            [{"role": "user", "content": "b", "entities": [], "meta": {}}],
            owner_type="user",
            owner_id="2",
            user_id=2,
        )


def test_start_conversation_rejects_other_owner(tmp_path, monkeypatch):
    from src.memory.service import MemoryService, ConversationState
    from src.core.config import settings

    monkeypatch.setattr(settings, "PERSIST_CONVERSATIONS_TO_DB", False)
    monkeypatch.setattr(settings, "VECTOR_DB_PATH", str(tmp_path))

    mem = MemoryService()
    doc = "doc-x"
    cid = "conv-owned"
    mem.save_conversation(
        ConversationState(conversation_id=cid, document_id=doc, owner_type="user", owner_id="1"),
        owner_type="user",
        owner_id="1",
        user_id=1,
    )
    with pytest.raises(PermissionError):
        mem.start_conversation(
            doc, cid, owner_type="user", owner_id="2", user_id=2
        )


def test_worker_health_strips_job_ids(client, monkeypatch):
    from src.db import jobs as job_store

    def fake_heartbeats(**_k):
        return [
            {
                "worker_id": "w1",
                "hostname": "host",
                "status": "busy",
                "alive": True,
                "last_seen_at": "2026-01-01T00:00:00+00:00",
                "meta": {"current_job_id": "secret-job-uuid-1234"},
            }
        ]

    monkeypatch.setattr(job_store, "list_worker_heartbeats", fake_heartbeats)
    r = client.get("/api/worker/health")
    assert r.status_code in (200, 503)
    body = r.json()
    blob = str(body)
    assert "secret-job-uuid-1234" not in blob
    assert "current_job_id" not in blob
    workers = body.get("workers") or []
    assert workers and "busy" in workers[0]
