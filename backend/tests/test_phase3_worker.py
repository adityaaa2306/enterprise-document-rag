"""Phase 3 — durable Postgres/SQLite job queue + worker claim/reclaim."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def phase3_env(tmp_path, monkeypatch):
    root = tmp_path / "object_store"
    root.mkdir()
    db_path = tmp_path / "phase3.sqlite"
    db_url = f"sqlite:///{db_path.as_posix()}"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("JWT_SECRET_KEY", "phase3-test-secret-key-32chars!!")
    monkeypatch.setenv("CORS_ALLOW_ALL", "true")
    monkeypatch.setenv("OBJECT_STORAGE_BACKEND", "local")
    monkeypatch.setenv("OBJECT_STORAGE_LOCAL_ROOT", str(root))
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("AUTO_CREATE_SCHEMA", "true")
    monkeypatch.setenv("PERSIST_JOBS_TO_DB", "true")
    monkeypatch.setenv("WORKER_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("WORKER_CLAIM_TIMEOUT_SEC", "60")
    monkeypatch.setenv("WORKER_RETRY_BACKOFF_SEC", "1")
    monkeypatch.setenv("WORKER_HEARTBEAT_STALE_SEC", "30")
    monkeypatch.setenv("ENABLE_UNDERSTANDING", "false")

    from src.core.config import settings
    from src.db.session import init_engine
    from src.storage.factory import reset_object_storage_cache

    monkeypatch.setattr(settings, "APP_ENV", "testing")
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "phase3-test-secret-key-32chars!!")
    monkeypatch.setattr(settings, "CORS_ALLOW_ALL", True)
    monkeypatch.setattr(settings, "OBJECT_STORAGE_BACKEND", "local")
    monkeypatch.setattr(settings, "OBJECT_STORAGE_LOCAL_ROOT", str(root))
    monkeypatch.setattr(settings, "DATABASE_URL", db_url)
    monkeypatch.setattr(settings, "AUTO_CREATE_SCHEMA", True)
    monkeypatch.setattr(settings, "RUN_MIGRATIONS_ON_STARTUP", False)
    monkeypatch.setattr(settings, "PERSIST_JOBS_TO_DB", True)
    monkeypatch.setattr(settings, "WORKER_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(settings, "WORKER_CLAIM_TIMEOUT_SEC", 60)
    monkeypatch.setattr(settings, "WORKER_RETRY_BACKOFF_SEC", 1)
    monkeypatch.setattr(settings, "WORKER_HEARTBEAT_STALE_SEC", 30)
    monkeypatch.setattr(settings, "ENABLE_UNDERSTANDING", False)

    reset_object_storage_cache()
    engine = init_engine(db_url)

    from src.db.base import Base
    import src.db.models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    from src.memory import storage as mem_storage

    if hasattr(mem_storage, "_sync_session_aliases"):
        mem_storage._sync_session_aliases()

    from src.agents import models as agent_models

    monkeypatch.setattr(agent_models, "load_all_models", lambda: None)

    yield {"root": root, "db_url": db_url}
    reset_object_storage_cache()


@pytest.fixture()
def client(phase3_env):
    from src.api.main import app

    with TestClient(app) as c:
        yield c


def _register_login(client: TestClient):
    email = f"p3-{uuid.uuid4().hex[:10]}@example.com"
    assert client.post(
        "/auth/register",
        json={"email": email, "password": "SecurePass123", "full_name": "P3"},
    ).status_code == 200
    r = client.post("/auth/login", json={"email": email, "password": "SecurePass123"})
    assert r.status_code == 200
    return r.json()


def test_summarize_enqueues_pending_only(client):
    tokens = _register_login(client)
    files = {"file": ("doc.pdf", b"%PDF-1.4 phase3", "application/pdf")}
    r = client.post(
        "/summarize",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        files=files,
    )
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]

    st = client.get(
        f"/job-status/{job_id}",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert st.status_code == 200, st.text
    body = st.json()
    assert body["status"] == "pending"
    assert body["progress"] == 0.0


def test_claim_is_exclusive(phase3_env):
    from src.db import jobs as job_store
    from src.core.job_status import STATUS_PENDING, STATUS_PROCESSING

    jid = str(uuid.uuid4())
    job_store.enqueue_job(jid, user_id=None, filename="a.pdf", job_mode="automatic")
    assert job_store.get_job(jid)["status"] == STATUS_PENDING

    a = job_store.claim_next_job("worker-a")
    assert a is not None
    assert a["job_id"] == jid
    assert a["status"] == STATUS_PROCESSING
    assert a["claimed_by"] == "worker-a"
    assert a["attempt_count"] == 1

    b = job_store.claim_next_job("worker-b")
    assert b is None  # already claimed


def test_reclaim_stale_processing(phase3_env):
    from src.db import jobs as job_store
    from src.core.job_status import STATUS_PENDING, STATUS_PROCESSING
    from src.db.models import JobModel
    from src.db.session import get_session

    jid = str(uuid.uuid4())
    job_store.enqueue_job(jid, filename="stale.pdf")
    claimed = job_store.claim_next_job("dead-worker")
    assert claimed["status"] == STATUS_PROCESSING

    # Force heartbeat into the past
    old = datetime.now(timezone.utc) - timedelta(seconds=3600)
    db = get_session()
    try:
        row = db.get(JobModel, jid)
        row.heartbeat_at = old
        row.claimed_at = old
        db.commit()
    finally:
        db.close()
    job_store.JOB_STATUSES.pop(jid, None)

    n = job_store.reclaim_stale_jobs(stale_after_sec=60, max_attempts=3)
    assert n == 1
    job = job_store.get_job(jid)
    assert job["status"] == STATUS_PENDING
    assert job.get("claimed_by") is None


def test_fail_or_retry_then_terminal(phase3_env):
    from src.db import jobs as job_store
    from src.core.job_status import STATUS_PENDING, STATUS_ERROR
    from src.core.config import settings

    jid = str(uuid.uuid4())
    job_store.enqueue_job(jid, filename="retry.pdf")
    job_store.claim_next_job("w1")  # attempt 1
    out = job_store.fail_or_retry_job(jid, error="boom1")
    assert out["status"] == STATUS_PENDING

    # Make available immediately
    job_store.upsert_job(jid, available_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    job_store.JOB_STATUSES.pop(jid, None)

    job_store.claim_next_job("w1")  # attempt 2
    job_store.fail_or_retry_job(jid, error="boom2")
    job_store.upsert_job(jid, available_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    job_store.JOB_STATUSES.pop(jid, None)

    job_store.claim_next_job("w1")  # attempt 3
    out = job_store.fail_or_retry_job(jid, error="boom3")
    # After 3 attempts, next fail is terminal
    assert out["status"] == STATUS_ERROR
    assert settings.WORKER_MAX_ATTEMPTS == 3


def test_worker_processes_claimed_job(phase3_env, monkeypatch):
    from src.db import jobs as job_store
    from src.memory import storage
    from src.storage import get_object_storage
    from src.core.job_status import STATUS_COMPLETE
    from src.worker.runner import process_claimed_job

    jid = str(uuid.uuid4())
    key = f"documents/anon/{jid}/t.pdf"
    get_object_storage().put_bytes(key, b"%PDF-1.4 x", content_type="application/pdf", original_filename="t.pdf")
    storage.save_document_file_metadata(
        jid,
        user_id=None,
        storage_key=key,
        original_filename="t.pdf",
        content_type="application/pdf",
        byte_size=10,
    )
    job_store.enqueue_job(jid, user_id=None, filename="t.pdf", job_mode="automatic")
    claimed = job_store.claim_next_job("test-worker")
    assert claimed is not None

    def fake_invoke(state):
        return {
            **state,
            "final_summary": "hello from fake graph",
            "carbon_report": {"carbon_saved_grams": 1.0, "message": "ok"},
            "routing_decision": {"selected_model": "fake"},
            "job_latency_ms": 12.0,
        }

    monkeypatch.setattr("src.worker.runner.agentic_graph.invoke", fake_invoke)
    process_claimed_job(claimed, worker_id="test-worker")

    done = job_store.get_job(jid)
    assert done["status"] == STATUS_COMPLETE
    assert done["result"]["final_summary"] == "hello from fake graph"


def test_worker_health_endpoint(client, phase3_env):
    from src.db import jobs as job_store

    r = client.get("/api/worker/health")
    assert r.status_code == 503
    assert r.json()["alive_count"] == 0

    job_store.upsert_worker_heartbeat("w-live", status="idle")
    r2 = client.get("/api/worker/health")
    assert r2.status_code == 200
    body = r2.json()
    assert body["alive_count"] >= 1
    assert any(w["worker_id"] == "w-live" for w in body["workers"])
