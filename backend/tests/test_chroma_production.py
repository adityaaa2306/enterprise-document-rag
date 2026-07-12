"""Embedded Chroma PersistentClient — no remote server."""
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
    monkeypatch.setattr(settings, "CHROMA_PERSIST_DIRECTORY", str(root))
    monkeypatch.setattr(settings, "VECTOR_DB_PATH", str(tmp_path / "aux"))
    monkeypatch.setattr(settings, "CHROMA_COLLECTION_NAME", "test_collection")
    monkeypatch.setattr(settings, "CHUNK_COLLECTION_NAME", "")
    reset_chroma_client()
    yield root
    reset_chroma_client()


def test_persist_directory_created(monkeypatch, tmp_path):
    from src.core.config import settings
    from src.memory.chroma import chroma_persist_directory, reset_chroma_client

    target = tmp_path / "nested" / "chroma"
    monkeypatch.setattr(settings, "CHROMA_PERSIST_DIRECTORY", str(target))
    reset_chroma_client()
    path = chroma_persist_directory()
    assert Path(path).is_dir()
    assert path == str(target.resolve())


def test_persistent_client_roundtrip(chroma_tmp):
    from src.memory.chroma import get_chroma_client, chroma_health_check, reset_chroma_client
    from src.core.config import settings

    reset_chroma_client()
    health = chroma_health_check()
    assert health["ok"] is True
    assert health["mode"] == "persistent"
    assert "path" in health

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


def test_init_chroma_returns_immediately(chroma_tmp):
    from src.memory.chroma import init_chroma, reset_chroma_client

    reset_chroma_client()
    out = init_chroma()
    assert out["ok"] is True


def test_compose_uses_embedded_chroma_volume():
    text = Path(__file__).resolve().parents[1].joinpath("docker-compose.yml").read_text(encoding="utf-8")
    assert "CHROMA_PERSIST_DIRECTORY" in text
    assert "chroma_data:" in text
    assert "chromadb/chroma" not in text
    assert "CHROMA_SERVER_HOST" not in text
    assert "HttpClient" not in text


def test_render_blueprint_uses_embedded_worker():
    """Portfolio Render path must share Chroma via embedded worker (no split disks)."""
    root = Path(__file__).resolve().parents[2]
    for rel in ("render.yaml", "backend/render.yaml"):
        text = (root / rel).read_text(encoding="utf-8")
        assert "dockerBuildTarget: api" in text
        assert "RUN_EMBEDDED_WORKER" in text
        assert 'value: "true"' in text or "value: 'true'" in text
        # Separate worker service would use a different disk — not in default blueprint
        assert "type: worker" not in text


def test_api_entrypoint_avoids_wait_n():
    raw = Path(__file__).resolve().parents[1].joinpath(
        "scripts/docker-entrypoint-api.sh"
    ).read_text(encoding="utf-8")
    # Strip comments — docs may mention wait -n as the anti-pattern
    code = "\n".join(
        line for line in raw.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    assert "wait -n" not in code
    assert "RUN_EMBEDDED_WORKER" in code
    assert "_monitor_children" in code


def test_no_http_client_in_chroma_module():
    text = Path(__file__).resolve().parents[1].joinpath("src/memory/chroma.py").read_text(encoding="utf-8")
    assert "wait_for_chroma" not in text
    assert "PersistentClient" in text
    assert "chromadb.HttpClient" not in text
    assert "CHROMA_SERVER_HOST" not in text
