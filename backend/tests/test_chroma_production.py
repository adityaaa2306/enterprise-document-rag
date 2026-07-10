"""Chroma production client — mode resolution + persistent fallback (no server required)."""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest


@pytest.fixture()
def chroma_tmp(tmp_path, monkeypatch):
    from src.core.config import settings
    from src.memory.chroma import reset_chroma_client

    root = tmp_path / "chroma"
    root.mkdir()
    monkeypatch.setattr(settings, "VECTOR_DB_PATH", str(root))
    monkeypatch.setattr(settings, "CHROMA_MODE", "persistent")
    monkeypatch.setattr(settings, "CHROMA_SERVER_HOST", "")
    monkeypatch.setattr(settings, "CHROMA_COLLECTION_NAME", "test_collection")
    monkeypatch.setattr(settings, "CHUNK_COLLECTION_NAME", "")
    reset_chroma_client()
    yield root
    reset_chroma_client()


def test_chroma_mode_auto_http_when_host_set(monkeypatch):
    from src.core.config import settings
    from src.memory.chroma import chroma_mode, reset_chroma_client

    monkeypatch.setattr(settings, "CHROMA_MODE", "auto")
    monkeypatch.setattr(settings, "CHROMA_SERVER_HOST", "chroma")
    reset_chroma_client()
    assert chroma_mode() == "http"


def test_chroma_mode_explicit_persistent(monkeypatch):
    from src.core.config import settings
    from src.memory.chroma import chroma_mode, reset_chroma_client

    monkeypatch.setattr(settings, "CHROMA_MODE", "persistent")
    monkeypatch.setattr(settings, "CHROMA_SERVER_HOST", "chroma")  # ignored when explicit
    reset_chroma_client()
    assert chroma_mode() == "persistent"


def test_persistent_client_roundtrip(chroma_tmp):
    from src.memory.chroma import get_chroma_client, chroma_health_check, reset_chroma_client
    from src.core.config import settings

    reset_chroma_client()
    health = chroma_health_check()
    assert health["ok"] is True
    assert health["mode"] == "persistent"

    client = get_chroma_client()
    col = client.get_or_create_collection(name=settings.chroma_collection())
    cid = f"c-{uuid.uuid4().hex[:8]}"
    col.add(
        ids=[cid],
        embeddings=[[0.1, 0.2, 0.3]],
        documents=["hello chroma"],
        metadatas=[{"document_id": "doc-1"}],
    )
    got = col.get(ids=[cid], include=["documents", "metadatas"])
    assert got["ids"] == [cid]
    assert got["documents"][0] == "hello chroma"


def test_http_mode_requires_host(monkeypatch):
    from src.core.config import settings
    from src.memory.chroma import get_chroma_client, reset_chroma_client

    monkeypatch.setattr(settings, "CHROMA_MODE", "http")
    monkeypatch.setattr(settings, "CHROMA_SERVER_HOST", "")
    reset_chroma_client()
    with pytest.raises(RuntimeError, match="CHROMA_SERVER_HOST"):
        get_chroma_client()


def test_wait_for_chroma_retries_then_succeeds(monkeypatch, chroma_tmp):
    from src.memory import chroma as chroma_mod
    from src.core.config import settings

    chroma_mod.reset_chroma_client()
    calls = {"n": 0}
    real_health = chroma_mod.chroma_health_check

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            chroma_mod.reset_chroma_client()
            return {"ok": False, "mode": "persistent", "error": "simulated"}
        return real_health()

    sleeps = []
    monkeypatch.setattr(chroma_mod, "chroma_health_check", flaky)
    monkeypatch.setattr(chroma_mod.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(settings, "CHROMA_STARTUP_REQUIRED", True)

    out = chroma_mod.wait_for_chroma(
        max_wait_sec=30,
        initial_delay_sec=0.1,
        max_delay_sec=1.0,
        required=True,
    )
    assert out["ok"] is True
    assert calls["n"] >= 3
    assert sleeps  # backoff occurred
    assert sleeps[0] == pytest.approx(0.1)
    if len(sleeps) > 1:
        assert sleeps[1] == pytest.approx(0.2)


def test_wait_for_chroma_raises_when_required(monkeypatch):
    from src.memory import chroma as chroma_mod
    from src.memory.chroma import ChromaUnavailableError

    chroma_mod.reset_chroma_client()
    monkeypatch.setattr(
        chroma_mod,
        "chroma_health_check",
        lambda: {"ok": False, "mode": "http", "error": "down"},
    )
    monkeypatch.setattr(chroma_mod.time, "sleep", lambda s: None)

    with pytest.raises(ChromaUnavailableError):
        chroma_mod.wait_for_chroma(
            max_wait_sec=0.3,
            initial_delay_sec=0.05,
            max_delay_sec=0.1,
            required=True,
        )


def test_compose_uses_chroma_http_service():
    text = Path(__file__).resolve().parents[1].joinpath("docker-compose.yml").read_text(encoding="utf-8")
    assert "chroma:" in text
    assert "CHROMA_MODE: http" in text
    assert "CHROMA_SERVER_HOST: chroma" in text
    assert "chromadb/chroma" in text
