"""Guest Mode — owner abstraction, session lifecycle, upgrade."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    root = tmp_path / "object_store"
    root.mkdir()
    db_path = tmp_path / "guest.sqlite"
    db_url = f"sqlite:///{db_path.as_posix()}"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("CORS_ALLOW_ALL", "true")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-for-guest-mode!!!!")
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("AUTO_CREATE_SCHEMA", "true")
    monkeypatch.setenv("OBJECT_STORAGE_BACKEND", "local")
    monkeypatch.setenv("OBJECT_STORAGE_LOCAL_ROOT", str(root))
    monkeypatch.setenv("CHROMA_PERSIST_DIRECTORY", str(tmp_path / "chroma"))
    monkeypatch.setenv("VECTOR_DB_PATH", str(tmp_path / "aux"))
    monkeypatch.setenv("RUN_EMBEDDED_WORKER", "false")
    monkeypatch.setenv("PERSIST_JOBS_TO_DB", "true")

    from src.core.config import settings
    from src.db.session import init_engine
    from src.storage.factory import reset_object_storage_cache

    monkeypatch.setattr(settings, "APP_ENV", "testing")
    monkeypatch.setattr(settings, "CORS_ALLOW_ALL", True)
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "test-secret-key-for-guest-mode!!!!")
    monkeypatch.setattr(settings, "DATABASE_URL", db_url)
    monkeypatch.setattr(settings, "AUTO_CREATE_SCHEMA", True)
    monkeypatch.setattr(settings, "OBJECT_STORAGE_BACKEND", "local")
    monkeypatch.setattr(settings, "OBJECT_STORAGE_LOCAL_ROOT", str(root))
    monkeypatch.setattr(settings, "CHROMA_PERSIST_DIRECTORY", str(tmp_path / "chroma"))
    monkeypatch.setattr(settings, "VECTOR_DB_PATH", str(tmp_path / "aux"))
    monkeypatch.setattr(settings, "RUN_EMBEDDED_WORKER", False)
    monkeypatch.setattr(settings, "PERSIST_JOBS_TO_DB", True)

    reset_object_storage_cache()
    engine = init_engine(db_url)

    from src.db.base import Base
    import src.db.models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    from src.agents import models as agent_models
    from src.memory import chroma as chroma_mod
    from src.memory import storage as mem_storage

    monkeypatch.setattr(agent_models, "load_all_models", lambda: None)
    monkeypatch.setattr(
        chroma_mod,
        "chroma_health_check",
        lambda: {"ok": True, "mode": "persistent", "path": str(tmp_path), "ready": True},
    )
    monkeypatch.setattr(chroma_mod, "is_chroma_ready", lambda: True)
    if hasattr(mem_storage, "_sync_session_aliases"):
        mem_storage._sync_session_aliases()

    from src.api.main import app

    with TestClient(app) as c:
        yield c

    reset_object_storage_cache()


def test_guest_session_create_and_cookie(client):
    r = client.post("/guest/session")
    assert r.status_code == 200
    body = r.json()
    assert body["guest_session_id"]
    assert body["anonymous_name"].startswith("Guest-")
    assert "ga_guest_session" in r.cookies


def test_guest_can_list_jobs_with_header(client):
    r = client.post("/guest/session")
    sid = r.json()["guest_session_id"]
    r2 = client.get("/jobs", headers={"X-Guest-Session-Id": sid})
    assert r2.status_code == 200
    assert r2.json()["count"] == 0


def test_guest_upload_enqueue(client):
    r = client.post("/guest/session")
    sid = r.json()["guest_session_id"]
    files = {"file": ("demo.pdf", b"%PDF-1.4 guest demo content", "application/pdf")}
    r2 = client.post(
        "/summarize?mode=automatic",
        files=files,
        headers={"X-Guest-Session-Id": sid},
    )
    assert r2.status_code == 200, r2.text
    data = r2.json()
    assert data["job_id"]
    st = client.get(f"/job-status/{data['job_id']}", headers={"X-Guest-Session-Id": sid})
    assert st.status_code == 200


def test_guest_cannot_access_other_guest_job(client):
    a = client.post("/guest/session").json()["guest_session_id"]
    client.cookies.clear()
    b = client.post("/guest/session").json()["guest_session_id"]
    assert a != b
    files = {"file": ("a.pdf", b"%PDF-1.4 aaa", "application/pdf")}
    job = client.post("/summarize", files=files, headers={"X-Guest-Session-Id": a}).json()
    forbidden = client.get(
        f"/job-status/{job['job_id']}",
        headers={"X-Guest-Session-Id": b},
    )
    assert forbidden.status_code in (403, 404)


def test_guest_upgrade_transfers_job(client):
    guest = client.post("/guest/session").json()["guest_session_id"]
    files = {"file": ("u.pdf", b"%PDF-1.4 upgrade", "application/pdf")}
    job = client.post("/summarize", files=files, headers={"X-Guest-Session-Id": guest}).json()

    email = "guest-upgrade@example.com"
    client.post(
        "/auth/register",
        json={"email": email, "password": "SecurePass123!", "full_name": "Upgrader"},
    )
    login = client.post(
        "/auth/login",
        json={"email": email, "password": "SecurePass123!"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    up = client.post(
        "/guest/upgrade",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Guest-Session-Id": guest,
        },
    )
    assert up.status_code == 200, up.text
    assert up.json().get("ok") is True

    st = client.get(
        f"/job-status/{job['job_id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert st.status_code == 200


def test_guest_expiration_and_cleanup(client):
    from src.db import guests as guest_store
    from src.db.models import GuestSessionModel
    from src.db.session import get_session

    sid = client.post("/guest/session").json()["guest_session_id"]
    db = get_session()
    try:
        row = db.get(GuestSessionModel, sid)
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    finally:
        db.close()

    report = guest_store.cleanup_expired_guests()
    assert report["cleaned"] >= 1
    sess = guest_store.get_guest_session(sid)
    assert sess is None or sess.get("status") in ("purged", "expired")


def test_cleanup_skips_guest_with_running_job(client):
    """Expired clock alone must not purge a guest while a job is pending/processing."""
    from src.core import job_status as job_status_mod
    from src.db import guests as guest_store
    from src.db import jobs as job_store
    from src.db.models import GuestSessionModel
    from src.db.session import get_session

    sid = client.post("/guest/session").json()["guest_session_id"]
    job_id = "guest-running-job-1"
    job_store.enqueue_job(
        job_id,
        owner_type="guest",
        owner_id=sid,
        filename="live.pdf",
        message="Queued",
    )
    assert job_store.get_job(job_id, include_result=False)["status"] == job_status_mod.STATUS_PENDING

    db = get_session()
    try:
        row = db.get(GuestSessionModel, sid)
        row.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()
    finally:
        db.close()

    report = guest_store.cleanup_expired_guests()
    assert report["cleaned"] == 0
    assert report.get("skipped_running", 0) == 0  # filtered out in SELECT
    # Session may be marked expired in a later pass; must still exist and not be purged
    sess = guest_store.get_guest_session(sid)
    assert sess is not None
    assert sess.get("status") != "purged"
    assert job_store.get_job(job_id, include_result=False) is not None

    # After job completes, cleanup may purge
    job_store.upsert_job(job_id, status=job_status_mod.STATUS_COMPLETE, progress=1.0)
    report2 = guest_store.cleanup_expired_guests()
    assert report2["cleaned"] >= 1
    sess2 = guest_store.get_guest_session(sid)
    assert sess2 is None or sess2.get("status") == "purged"


def test_guest_chat_conversation_stamps_owner(client):
    """Conversations created for guests must carry owner_type+owner_id."""
    from src.db import conversations as conv_db
    from src.db import jobs as job_store
    from src.memory.service import MemoryService

    sid = client.post("/guest/session").json()["guest_session_id"]
    job_id = "guest-conv-job-1"
    job_store.enqueue_job(
        job_id,
        owner_type="guest",
        owner_id=sid,
        filename="c.pdf",
    )
    mem = MemoryService()
    state = mem.start_conversation(
        job_id,
        owner_type="guest",
        owner_id=sid,
    )
    loaded = conv_db.load_conversation(state.conversation_id)
    assert loaded is not None
    assert loaded["owner_type"] == "guest"
    assert loaded["owner_id"] == sid
    assert loaded["document_id"] == job_id


def test_authenticated_flow_still_requires_jwt_or_guest(client):
    r = client.get("/jobs")
    assert r.status_code == 401
