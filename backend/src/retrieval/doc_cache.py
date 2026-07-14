"""
In-process document chunk cache for retrieval (query path).

Loads chunk text + metadata once per document_id and reuses across
BM25, meta lookup, and parent expansion — avoids repeated Postgres round-trips.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

_lock = threading.RLock()
# document_id -> {chunk_id: CachedChunk}
_CACHE: Dict[str, Dict[str, "CachedChunk"]] = {}
# document_id -> ordered chunk ids
_ORDER: Dict[str, List[str]] = {}


@dataclass(frozen=True)
class CachedChunk:
    chunk_id: str
    text: str
    parent_id: Optional[str]
    section_path: Optional[str]
    chunk_kind: Optional[str]
    chunk_index: int


def invalidate(document_id: str) -> None:
    with _lock:
        _CACHE.pop(document_id, None)
        _ORDER.pop(document_id, None)


def clear_all() -> None:
    with _lock:
        _CACHE.clear()
        _ORDER.clear()


def _load_from_db(document_id: str) -> Dict[str, CachedChunk]:
    from src.memory import storage

    db = storage._session()
    try:
        rows = (
            db.query(storage.ChunkModel)
            .filter(storage.ChunkModel.document_id == document_id)
            .order_by(storage.ChunkModel.chunk_index.asc())
            .all()
        )
        out: Dict[str, CachedChunk] = {}
        order: List[str] = []
        for r in rows:
            cid = r.id or f"{document_id}_{r.chunk_index}"
            out[cid] = CachedChunk(
                chunk_id=cid,
                text=r.text or "",
                parent_id=r.parent_id,
                section_path=r.section_path,
                chunk_kind=r.chunk_kind,
                chunk_index=int(r.chunk_index or 0),
            )
            order.append(cid)
        with _lock:
            _CACHE[document_id] = out
            _ORDER[document_id] = order
        log.debug("doc_cache loaded document_id=%s chunks=%s", document_id, len(out))
        return out
    finally:
        db.close()


def get_map(document_id: str) -> Dict[str, CachedChunk]:
    with _lock:
        hit = _CACHE.get(document_id)
    if hit is not None:
        return hit
    return _load_from_db(document_id)


def get_chunk(document_id: str, chunk_id: str) -> Optional[CachedChunk]:
    return get_map(document_id).get(chunk_id)


def text_map(document_id: str) -> Dict[str, str]:
    return {cid: c.text for cid, c in get_map(document_id).items()}


def siblings_of_parent(
    document_id: str, parent_id: str
) -> List[CachedChunk]:
    return [
        c
        for c in get_map(document_id).values()
        if c.parent_id == parent_id
    ]


def meta_for(document_id: str, chunk_id: str) -> Dict[str, Optional[str]]:
    c = get_chunk(document_id, chunk_id)
    if not c:
        return {}
    return {
        "parent_id": c.parent_id,
        "section_path": c.section_path,
        "chunk_kind": c.chunk_kind,
    }
