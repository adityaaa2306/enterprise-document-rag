"""
Background embedding prefetch — overlap store I/O with map/validate/compile.

Embeddings are of source chunk text (immutable after triage), so they can
safely run in parallel with summarization without changing any outputs.
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

_lock = threading.Lock()
# job_id → Future[List[Optional[List[float]]]]
_PENDING: Dict[str, Future] = {}
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="embed-prefetch")


def _embed_chunk_texts(texts: List[str]) -> List[Optional[List[float]]]:
    from src.agents import models

    if not texts:
        return []
    if models.get_nim_client() is None:
        return [None] * len(texts)
    try:
        vectors = models.embed_texts(texts)
        out: List[Optional[List[float]]] = []
        for i in range(len(texts)):
            out.append(vectors[i] if i < len(vectors) else None)
        return out
    except Exception as e:
        log.warning("embed prefetch failed: %s", e)
        return [None] * len(texts)


def start_embed_prefetch(job_id: str, chunks: List[Any]) -> None:
    """Kick off non-blocking embed of chunk source texts."""
    texts: List[str] = []
    for c in chunks or []:
        if hasattr(c, "content"):
            texts.append(str(c.content or ""))
        elif isinstance(c, dict):
            texts.append(str(c.get("content") or c.get("text") or ""))
        else:
            texts.append(str(c or ""))

    with _lock:
        old = _PENDING.pop(job_id, None)
        if old is not None and not old.done():
            old.cancel()
        fut = _EXECUTOR.submit(_embed_chunk_texts, texts)
        _PENDING[job_id] = fut
    log.info("embed prefetch started job_id=%s chunks=%s", job_id, len(texts))


def get_embed_prefetch(
    job_id: str,
    *,
    timeout_sec: float = 120.0,
) -> Optional[List[Optional[List[float]]]]:
    """Block briefly for prefetch result; return None on miss/timeout."""
    with _lock:
        fut = _PENDING.get(job_id)
    if fut is None:
        return None
    try:
        result = fut.result(timeout=timeout_sec)
        with _lock:
            _PENDING.pop(job_id, None)
        return result
    except Exception as e:
        log.warning("embed prefetch wait failed job_id=%s: %s", job_id, e)
        with _lock:
            _PENDING.pop(job_id, None)
        return None


def cancel_embed_prefetch(job_id: str) -> None:
    with _lock:
        fut = _PENDING.pop(job_id, None)
    if fut is not None and not fut.done():
        fut.cancel()
