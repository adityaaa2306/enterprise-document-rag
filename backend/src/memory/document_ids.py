"""
Canonical document_id helpers (Phase 2.0).

Public convention: document_id == job_id (UUID from POST /summarize).
Use that value for Chroma filters and POST /rag-query.
"""
from __future__ import annotations

from typing import Any, List


def align_chunks_to_document_id(document_id: str, chunks: List[Any]) -> List[Any]:
    """
    Ensure every chunk object/dict carries ``document_id`` equal to the
    canonical storage key (job_id). Does not change chunk text content.
    """
    aligned: List[Any] = []
    for c in chunks:
        if hasattr(c, "model_copy"):
            try:
                aligned.append(c.model_copy(update={"document_id": document_id}))
                continue
            except Exception:
                pass
        if hasattr(c, "document_id"):
            try:
                setattr(c, "document_id", document_id)
            except Exception:
                pass
            aligned.append(c)
            continue
        if isinstance(c, dict):
            d = dict(c)
            d["document_id"] = document_id
            aligned.append(d)
            continue
        aligned.append(c)
    return aligned
