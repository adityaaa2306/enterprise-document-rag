"""
Query-path guard — detect accidental ingestion work during /rag-query.

Does not change pipeline behavior; only records/logs violations when
ingest-only operations are invoked while a RAG query is active.
"""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List

log = logging.getLogger(__name__)

_local = threading.local()

# Operations that must NEVER run on the chat/query path.
INGEST_ONLY_OPS = (
    "ocr",
    "layout_parsing",
    "heading_extraction",
    "table_extraction",
    "image_analysis",
    "chunk_generation",
    "document_embedding_generation",
    "vector_index_rebuild",
    "markdown_conversion",
    "document_parse",
)


def _state() -> Dict[str, Any]:
    if not hasattr(_local, "state"):
        _local.state = {"active": False, "violations": []}
    return _local.state


def begin_query_path(document_id: str = "", query: str = "") -> None:
    st = _state()
    st["active"] = True
    st["document_id"] = document_id
    st["query"] = (query or "")[:120]
    st["violations"] = []


def end_query_path() -> List[Dict[str, Any]]:
    st = _state()
    viol = list(st.get("violations") or [])
    st["active"] = False
    st["violations"] = []
    return viol


def is_query_path_active() -> bool:
    return bool(_state().get("active"))


def note_ingest_op(op: str, *, detail: str = "") -> None:
    """Call from ingest-only code paths. No-op if not on query path."""
    st = _state()
    if not st.get("active"):
        return
    entry = {"op": op, "detail": (detail or "")[:200]}
    st.setdefault("violations", []).append(entry)
    log.error(
        "QUERY_PATH_VIOLATION op=%s document_id=%s detail=%s",
        op,
        st.get("document_id"),
        detail[:200],
    )


@contextmanager
def query_path_scope(*, document_id: str = "", query: str = "") -> Iterator[None]:
    begin_query_path(document_id=document_id, query=query)
    try:
        yield
    finally:
        end_query_path()


def snapshot_violations() -> List[Dict[str, Any]]:
    return list(_state().get("violations") or [])
