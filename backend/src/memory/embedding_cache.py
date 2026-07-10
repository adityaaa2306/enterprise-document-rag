"""
Content-addressed embedding cache (Phase 2.B).

Key = sha256(model_id + "\\n" + text). Stored as JSON under VECTOR_DB_PATH/embed_cache/.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from typing import Dict, List, Optional, Tuple

from src.core.config import settings

log = logging.getLogger(__name__)
_lock = threading.Lock()
_hits = 0
_misses = 0


def _cache_dir() -> str:
    path = os.path.join(settings.VECTOR_DB_PATH, "embed_cache")
    os.makedirs(path, exist_ok=True)
    return path


def text_hash(model_id: str, text: str) -> str:
    h = hashlib.sha256()
    h.update(model_id.encode("utf-8"))
    h.update(b"\n")
    h.update(text.encode("utf-8"))
    return h.hexdigest()


def _path_for(key: str) -> str:
    return os.path.join(_cache_dir(), f"{key}.json")


def get_cached(model_id: str, text: str) -> Optional[List[float]]:
    global _hits, _misses
    key = text_hash(model_id, text)
    path = _path_for(key)
    try:
        if not os.path.exists(path):
            with _lock:
                _misses += 1
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        vec = data.get("embedding")
        if not isinstance(vec, list):
            with _lock:
                _misses += 1
            return None
        with _lock:
            _hits += 1
        return vec
    except Exception as e:
        log.warning(f"Embed cache read failed: {e}")
        with _lock:
            _misses += 1
        return None


def put_cached(model_id: str, text: str, embedding: List[float]) -> None:
    key = text_hash(model_id, text)
    path = _path_for(key)
    try:
        payload = {
            "model": model_id,
            "embedding": embedding,
            "dim": len(embedding),
        }
        tmp = path + ".tmp"
        with _lock:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            os.replace(tmp, path)
    except Exception as e:
        log.warning(f"Embed cache write failed: {e}")


def get_many(model_id: str, texts: List[str]) -> Tuple[List[Optional[List[float]]], List[int]]:
    """
    Returns (vectors_or_none aligned to texts, list of miss indices).
    """
    out: List[Optional[List[float]]] = []
    misses: List[int] = []
    for i, t in enumerate(texts):
        v = get_cached(model_id, t)
        out.append(v)
        if v is None:
            misses.append(i)
    return out, misses


def put_many(model_id: str, texts: List[str], embeddings: List[List[float]]) -> None:
    for t, e in zip(texts, embeddings):
        put_cached(model_id, t, e)


def stats() -> Dict[str, int]:
    with _lock:
        return {"hits": _hits, "misses": _misses}


def reset_stats() -> None:
    global _hits, _misses
    with _lock:
        _hits = 0
        _misses = 0
