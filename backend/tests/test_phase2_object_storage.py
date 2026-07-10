"""Phase 2 — object storage (local backend) + upload metadata."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def object_root(tmp_path, monkeypatch):
    root = tmp_path / "object_store"
    root.mkdir()
    db_path = tmp_path / "phase2.sqlite"
    db_url = f"sqlite:///{db_path.as_posix()}"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("JWT_SECRET_KEY", "phase2-test-secret-key-32chars!!")
    monkeypatch.setenv("CORS_ALLOW_ALL", "true")
    monkeypatch.setenv("OBJECT_STORAGE_BACKEND", "local")
    monkeypatch.setenv("OBJECT_STORAGE_LOCAL_ROOT", str(root))
    monkeypatch.setenv("AUTH_COOKIE_ENABLED", "false")
    monkeypatch.setenv("PERSIST_JOBS_TO_DB", "true")
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("AUTO_CREATE_SCHEMA", "true")

    from src.core.config import settings
    from src.db.session import init_engine
    from src.storage.factory import reset_object_storage_cache

    monkeypatch.setattr(settings, "APP_ENV", "testing")
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "phase2-test-secret-key-32chars!!")
    monkeypatch.setattr(settings, "CORS_ALLOW_ALL", True)
    monkeypatch.setattr(settings, "OBJECT_STORAGE_BACKEND", "local")
    monkeypatch.setattr(settings, "OBJECT_STORAGE_LOCAL_ROOT", str(root))
    monkeypatch.setattr(settings, "DATABASE_URL", db_url)
    monkeypatch.setattr(settings, "AUTO_CREATE_SCHEMA", True)
    monkeypatch.setattr(settings, "RUN_MIGRATIONS_ON_STARTUP", False)

    reset_object_storage_cache()
    engine = init_engine(db_url)

    from src.db.base import Base
    import src.db.models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    from src.agents import models as agent_models

    monkeypatch.setattr(agent_models, "load_all_models", lambda: None)

    # Keep memory.storage session aliases in sync with the new engine
    from src.memory import storage as mem_storage

    if hasattr(mem_storage, "_sync_session_aliases"):
        mem_storage._sync_session_aliases()

    yield root
    reset_object_storage_cache()


@pytest.fixture()
def client(object_root):
    from src.api.main import app

    with TestClient(app) as c:
        yield c


def _register_login(client: TestClient):
    email = f"p2-{uuid.uuid4().hex[:10]}@example.com"
    r = client.post(
        "/auth/register",
        json={"email": email, "password": "SecurePass123", "full_name": "Phase2 User"},
    )
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"email": email, "password": "SecurePass123"})
    assert r.status_code == 200, r.text
    return r.json()


def test_local_object_storage_roundtrip(object_root):
    from src.storage import get_object_storage
    from src.storage.factory import reset_object_storage_cache

    reset_object_storage_cache()
    store = get_object_storage()
    assert store.backend_name == "local"
    assert store.health_check() is True

    key = "documents/1/abc/test.pdf"
    data = b"%PDF-1.4 phase2-test"
    stored = store.put_bytes(key, data, content_type="application/pdf", original_filename="test.pdf")
    assert stored.storage_key == key
    assert stored.byte_size == len(data)
    assert store.exists(key)

    dest = object_root / "download.pdf"
    store.download_to_path(key, str(dest))
    assert dest.read_bytes() == data

    store.delete(key)
    assert not store.exists(key)


def test_ready_includes_object_storage(client):
    r = client.get("/api/ready")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["checks"]["object_storage"]["ok"] is True
    assert body["checks"]["object_storage"]["backend"] == "local"


def test_summarize_persists_storage_metadata(client, object_root):
    """Upload goes to object store; document row gets storage_key; job is pending."""
    tokens = _register_login(client)
    access = tokens["access_token"]

    files = {"file": ("sample.pdf", b"%PDF-1.4 hello phase2", "application/pdf")}
    r = client.post(
        "/summarize?mode=automatic",
        headers={"Authorization": f"Bearer {access}"},
        files=files,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    document_id = data["document_id"]

    from src.memory import storage
    from src.db import jobs as job_store
    from src.core.job_status import STATUS_PENDING

    key = storage.get_document_storage_key(document_id)
    assert key is not None
    assert document_id in key
    assert key.endswith("sample.pdf")

    from src.storage import get_object_storage

    store = get_object_storage()
    assert store.exists(key)
    on_disk = Path(object_root) / key.replace("/", os.sep)
    assert on_disk.is_file()
    assert on_disk.read_bytes().startswith(b"%PDF")

    job = job_store.get_job(document_id)
    assert job is not None
    assert job["status"] == STATUS_PENDING
