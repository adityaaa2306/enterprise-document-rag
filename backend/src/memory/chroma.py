"""
ChromaDB client factory (vector store only — not Postgres/pgvector).

Production (Render / multi-service): CHROMA_MODE=http → HttpClient to a
dedicated Chroma server with its own persistent disk.

Local single-process / tests: CHROMA_MODE=persistent → PersistentClient
under VECTOR_DB_PATH.

API and workers must use the same mode + collection so embeddings are shared.
Startup: wait_for_chroma() retries with exponential backoff before vector ops.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

from src.core.config import settings

log = logging.getLogger("memory.chroma")

_client: Any = None
_chroma_ready: bool = False


class ChromaUnavailableError(RuntimeError):
    """Raised when Chroma does not become healthy within the startup budget."""


def chroma_mode() -> str:
    """
    Resolve mode: http | persistent.

    Explicit CHROMA_MODE wins. Otherwise host set → http; else persistent.
    """
    raw = (getattr(settings, "CHROMA_MODE", "") or "").strip().lower()
    if raw in ("http", "server", "remote"):
        return "http"
    if raw in ("persistent", "embedded", "local"):
        return "persistent"
    host = (getattr(settings, "CHROMA_SERVER_HOST", "") or "").strip()
    return "http" if host else "persistent"


def reset_chroma_client() -> None:
    """Clear singleton (tests / after config change / failed connect)."""
    global _client, _chroma_ready
    _client = None
    _chroma_ready = False


def is_chroma_ready() -> bool:
    return _chroma_ready


def get_chroma_client() -> Any:
    """Lazy singleton Chroma client."""
    global _client
    if _client is None:
        _client = _build_chroma_client()
    return _client


def _build_chroma_client() -> Any:
    import chromadb

    mode = chroma_mode()
    if mode == "http":
        host = (getattr(settings, "CHROMA_SERVER_HOST", "") or "").strip()
        if not host:
            raise RuntimeError(
                "CHROMA_MODE=http requires CHROMA_SERVER_HOST "
                "(e.g. chroma service hostname on Render/Compose)"
            )
        port = int(getattr(settings, "CHROMA_SERVER_PORT", 8000) or 8000)
        ssl = bool(getattr(settings, "CHROMA_SERVER_SSL", False))
        headers = None
        token = (getattr(settings, "CHROMA_AUTH_TOKEN", "") or "").strip()
        if token:
            headers = {"Authorization": f"Bearer {token}"}
        log.info(
            "Chroma mode=http host=%s port=%s ssl=%s collection=%s",
            host,
            port,
            ssl,
            settings.chroma_collection(),
        )
        kwargs: dict = {"host": host, "port": port, "ssl": ssl}
        if headers:
            kwargs["headers"] = headers
        tenant = (getattr(settings, "CHROMA_TENANT", "") or "").strip()
        database = (getattr(settings, "CHROMA_DATABASE", "") or "").strip()
        if tenant:
            kwargs["tenant"] = tenant
        if database:
            kwargs["database"] = database
        return chromadb.HttpClient(**kwargs)

    path = os.path.abspath(settings.VECTOR_DB_PATH)
    os.makedirs(path, exist_ok=True)
    log.info(
        "Chroma mode=persistent path=%s collection=%s",
        path,
        settings.chroma_collection(),
    )
    return chromadb.PersistentClient(path=path)


def chroma_health_check() -> dict:
    """
    Probe Chroma for readiness. Returns a dict with ok/mode/details.
    On failure, clears the cached client so the next attempt reconnects.
    """
    mode = chroma_mode()
    try:
        client = get_chroma_client()
        beat = None
        if hasattr(client, "heartbeat"):
            beat = client.heartbeat()
        name = settings.chroma_collection()
        client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )
        out = {"ok": True, "mode": mode, "collection": name}
        if mode == "http":
            out["host"] = (settings.CHROMA_SERVER_HOST or "").strip()
            out["port"] = int(settings.CHROMA_SERVER_PORT or 8000)
            out["ssl"] = bool(settings.CHROMA_SERVER_SSL)
        else:
            out["path"] = os.path.abspath(settings.VECTOR_DB_PATH)
        if beat is not None:
            out["heartbeat"] = beat
        return out
    except Exception as e:
        log.warning("Chroma health check failed: %s", e)
        reset_chroma_client()
        return {"ok": False, "mode": mode, "error": str(e)}


def wait_for_chroma(
    *,
    max_wait_sec: Optional[float] = None,
    initial_delay_sec: Optional[float] = None,
    max_delay_sec: Optional[float] = None,
    required: Optional[bool] = None,
) -> dict:
    """
    Block until Chroma is healthy, using exponential backoff.

    Intended for API lifespan and worker process startup — not for per-query paths.
    """
    global _chroma_ready

    max_wait = float(
        max_wait_sec
        if max_wait_sec is not None
        else getattr(settings, "CHROMA_STARTUP_MAX_WAIT_SEC", 120.0)
    )
    delay = float(
        initial_delay_sec
        if initial_delay_sec is not None
        else getattr(settings, "CHROMA_STARTUP_INITIAL_DELAY_SEC", 0.5)
    )
    max_delay = float(
        max_delay_sec
        if max_delay_sec is not None
        else getattr(settings, "CHROMA_STARTUP_MAX_DELAY_SEC", 10.0)
    )
    must = (
        bool(required)
        if required is not None
        else bool(getattr(settings, "CHROMA_STARTUP_REQUIRED", True))
    )

    started = time.monotonic()
    attempt = 0
    last: dict = {"ok": False, "mode": chroma_mode(), "error": "not_started"}

    log.info(
        "Waiting for Chroma (mode=%s max_wait=%.1fs backoff=%.2f..%.1fs required=%s)",
        chroma_mode(),
        max_wait,
        delay,
        max_delay,
        must,
    )

    while True:
        attempt += 1
        last = chroma_health_check()
        if last.get("ok"):
            _chroma_ready = True
            elapsed = time.monotonic() - started
            log.info(
                "Chroma ready after %.2fs (attempt=%s mode=%s collection=%s)",
                elapsed,
                attempt,
                last.get("mode"),
                last.get("collection"),
            )
            return last

        elapsed = time.monotonic() - started
        remaining = max_wait - elapsed
        if remaining <= 0:
            break

        sleep_for = min(delay, remaining, max_delay)
        log.warning(
            "Chroma not ready (attempt=%s elapsed=%.1fs): %s — retry in %.2fs",
            attempt,
            elapsed,
            last.get("error") or last,
            sleep_for,
        )
        time.sleep(sleep_for)
        delay = min(delay * 2.0, max_delay)

    _chroma_ready = False
    msg = (
        f"Chroma unavailable after {max_wait:.1f}s / {attempt} attempt(s): "
        f"{last.get('error') or last}"
    )
    log.error(msg)
    if must:
        raise ChromaUnavailableError(msg)
    return last
