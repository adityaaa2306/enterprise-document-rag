"""Retrieval package (Phase 2.B)."""
from src.retrieval.rrf import reciprocal_rank_fusion

__all__ = [
    "reciprocal_rank_fusion",
    "RetrievalService",
    "RetrievalResult",
    "RetrievedPassage",
    "search_as_content_chunks",
    "bm25",
]


def __getattr__(name: str):
    if name in ("RetrievalService", "RetrievalResult", "RetrievedPassage", "search_as_content_chunks"):
        from src.retrieval import service as _svc

        return getattr(_svc, name)
    if name == "bm25":
        from src.retrieval import bm25 as _bm25

        return _bm25
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
