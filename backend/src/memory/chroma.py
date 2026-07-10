"""
ChromaDB client factory (vector store only — not Postgres/pgvector).

Portfolio / single-service deploy: chromadb.PersistentClient under
CHROMA_PERSIST_DIRECTORY (embedded on the API/Worker filesystem).

The application currently uses an embedded Chroma instance for cost-efficient
portfolio deployment. The production deployment architecture supports migrating
to a standalone Chroma server (HttpClient) with no application-level changes
beyond restoring an HttpClient branch in ``_build_chroma_client`` and pointing
env at that host — collection names and retrieval APIs stay the same.

Auxiliary files (BM25, embed cache, file conversations) use VECTOR_DB_PATH and
are separate from the Chroma persist directory.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from src.core.config import settings

log = logging.getLogger("memory.chroma")

_client: Any = None
_chroma_ready: bool = False


def reset_chroma_client() -> None:
    """Clear singleton (tests / after config change / failed init)."""
    global _client, _chroma_ready
    _client = None
    _chroma_ready = False


def is_chroma_ready() -> bool:
    return _chroma_ready


def chroma_persist_directory() -> str:
    """
    Absolute path for PersistentClient storage.

    Prefers CHROMA_PERSIST_DIRECTORY; falls back to VECTOR_DB_PATH for
    backward compatibility with older env files.
    """
    raw = (getattr(settings, "CHROMA_PERSIST_DIRECTORY", "") or "").strip()
    if not raw:
        raw = (getattr(settings, "VECTOR_DB_PATH", "") or "").strip() or "./local_db/chroma"
    path = os.path.abspath(raw)
    os.makedirs(path, exist_ok=True)
    return path


def get_chroma_client() -> Any:
    """Lazy singleton PersistentClient."""
    global _client
    if _client is None:
        _client = _build_chroma_client()
    return _client


def _build_chroma_client() -> Any:
    import chromadb

    path = chroma_persist_directory()
    log.info(
        "Chroma PersistentClient path=%s collection=%s",
        path,
        settings.chroma_collection(),
    )
    return chromadb.PersistentClient(path=path)


def init_chroma() -> dict:
    """
    Initialize PersistentClient + default collection. Returns immediately.
    Safe to call from FastAPI lifespan (no network wait loops).
    """
    return chroma_health_check()


def chroma_health_check() -> dict:
    """
    Verify embedded Chroma: persist dir writable, client opens, collection ready.
    No HTTP / remote checks.
    """
    try:
        path = chroma_persist_directory()
        if not os.path.isdir(path):
            return {
                "ok": False,
                "mode": "persistent",
                "error": f"persist directory missing: {path}",
            }
        if not os.access(path, os.R_OK | os.W_OK):
            return {
                "ok": False,
                "mode": "persistent",
                "error": f"persist directory not writable: {path}",
            }

        client = get_chroma_client()
        name = settings.chroma_collection()
        client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )
        global _chroma_ready
        _chroma_ready = True
        return {
            "ok": True,
            "mode": "persistent",
            "collection": name,
            "path": path,
            "ready": True,
        }
    except Exception as e:
        log.warning("Chroma health check failed: %s", e)
        reset_chroma_client()
        return {"ok": False, "mode": "persistent", "error": str(e)}
