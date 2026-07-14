"""
Query-path wall-clock timing (instrumentation only).

Used by RetrievalService / ContextAssembler / ResponseAgent / _run_rag_query
to produce a per-request stage breakdown without changing RAG logic.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

log = logging.getLogger(__name__)

# Canonical stage keys for the query path (imperative; not a LangGraph).
STAGE_QUERY_EMBED = "query_embed_ms"
STAGE_DENSE = "dense_retrieve_ms"
STAGE_BM25 = "bm25_retrieve_ms"
STAGE_RRF = "rrf_fuse_ms"
STAGE_RERANK = "rerank_ms"
STAGE_PARENT_EXPAND = "parent_expand_ms"
STAGE_RETRIEVAL_TOTAL = "retrieval_total_ms"
STAGE_CONTEXT_ASSEMBLE = "context_assemble_ms"
STAGE_GRAPH_SEED = "graph_seed_ms"
STAGE_META = "meta_lookup_ms"
STAGE_LLM_TTFT = "llm_ttft_ms"
STAGE_LLM_TTLT = "llm_ttlt_ms"
STAGE_LLM_TOTAL = "llm_generation_ms"
STAGE_NIM_REQUEST = "nim_request_ms"
STAGE_NIM_NETWORK = "nim_network_ms"
STAGE_EXPLAINABILITY = "explainability_ms"
STAGE_CITATIONS = "citations_ms"
STAGE_POSTPROCESS = "postprocess_ms"
STAGE_TOTAL = "total_ms"

# Ordered list for tables / waterfall UI
STAGE_DISPLAY_ORDER = [
    STAGE_QUERY_EMBED,
    STAGE_DENSE,
    STAGE_BM25,
    STAGE_GRAPH_SEED,
    STAGE_RRF,
    STAGE_META,
    STAGE_RERANK,
    STAGE_PARENT_EXPAND,
    STAGE_RETRIEVAL_TOTAL,
    STAGE_CONTEXT_ASSEMBLE,
    STAGE_NIM_REQUEST,
    STAGE_NIM_NETWORK,
    STAGE_LLM_TTFT,
    STAGE_LLM_TTLT,
    STAGE_LLM_TOTAL,
    STAGE_EXPLAINABILITY,
    STAGE_CITATIONS,
    STAGE_POSTPROCESS,
    STAGE_TOTAL,
]



class QueryLatencyTracker:
    """Accumulate stage durations (milliseconds) for one RAG request."""

    def __init__(self) -> None:
        self.stages: Dict[str, float] = {}
        self.meta: Dict[str, Any] = {}
        self._t0 = time.perf_counter()

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            self.stages[name] = round((time.perf_counter() - start) * 1000.0, 3)

    def set(self, name: str, duration_ms: float) -> None:
        self.stages[name] = round(float(duration_ms), 3)

    def add_meta(self, **kwargs: Any) -> None:
        self.meta.update(kwargs)

    def finish(self) -> Dict[str, Any]:
        """Close out total wall clock and return a JSON-serializable payload."""
        if STAGE_TOTAL not in self.stages:
            self.stages[STAGE_TOTAL] = round(
                (time.perf_counter() - self._t0) * 1000.0, 3
            )
        return self.as_dict()

    def as_dict(self) -> Dict[str, Any]:
        return {
            "stages_ms": dict(self.stages),
            "meta": dict(self.meta),
        }


def merge_latency(
    *parts: Optional[Dict[str, Any]],
    total_ms: Optional[float] = None,
) -> Dict[str, Any]:
    """Merge stage dicts from retrieval / assemble / LLM into one payload."""
    stages: Dict[str, float] = {}
    meta: Dict[str, Any] = {}
    for part in parts:
        if not part:
            continue
        stages.update(part.get("stages_ms") or {})
        meta.update(part.get("meta") or {})
    if total_ms is not None:
        stages[STAGE_TOTAL] = round(float(total_ms), 3)
    return {"stages_ms": stages, "meta": meta}


def log_query_latency(
    *,
    document_id: str,
    query: str,
    latency: Dict[str, Any],
) -> None:
    """Structured one-line log for easy grepping / table extraction."""
    stages = latency.get("stages_ms") or {}
    # Stable column order for copy/paste into a table
    order = list(STAGE_DISPLAY_ORDER)
    ordered = {k: stages[k] for k in order if k in stages}
    extras = {k: v for k, v in stages.items() if k not in ordered}
    ordered.update(extras)
    log.info(
        "query_latency document_id=%s query=%r stages_ms=%s meta=%s",
        document_id,
        (query or "")[:120],
        ordered,
        latency.get("meta") or {},
    )
