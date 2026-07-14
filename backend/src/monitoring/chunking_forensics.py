"""
Observation-only forensic recorder for adaptive chunking.

Does not alter control flow. Collectors are no-ops unless explicitly enabled.
"""
from __future__ import annotations

import json
import math
import os
import statistics
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence


def estimate_tokens(text: str) -> int:
    return max(1, len(text or "") // 4)


@dataclass
class SplitEvent:
    """One flush/split decision during semantic packing."""

    event_index: int
    reason: str  # new_heading | table_boundary | max_token_threshold | semantic_similarity_drop | forced_flush | end_of_document | consolidate_pack | force_cap
    detail: str = ""
    buffer_tokens_before: int = 0
    incoming_tokens: int = 0
    similarity: Optional[float] = None
    section_title: Optional[str] = None
    element_type: Optional[str] = None


@dataclass
class MergeEvent:
    reason: str
    detail: str = ""
    chunks_merged: int = 0
    tokens_before: int = 0
    tokens_after: int = 0
    similarity: Optional[float] = None
    section_title: Optional[str] = None


@dataclass
class ChunkForensicRecord:
    chunk_index: int
    page_range: Optional[str] = None
    section: Optional[str] = None
    heading: Optional[str] = None
    element_types: List[str] = field(default_factory=list)
    paragraphs: int = 0
    tables: int = 0
    images: int = 0
    estimated_tokens: int = 0
    char_count: int = 0
    reason_split: Optional[str] = None
    reason_merge: Optional[str] = None
    complexity: Optional[float] = None
    importance: Optional[float] = None
    router_decision: Optional[str] = None
    model: Optional[str] = None
    router_reason: Optional[str] = None
    expected_carbon_g: Optional[float] = None
    expected_latency_ms: Optional[float] = None
    content_preview: str = ""


@dataclass
class StageTiming:
    stage: str
    ms: float
    notes: str = ""


class ChunkingForensics:
    """Accumulates stage-level and per-decision diagnostics."""

    def __init__(self, enabled: bool = True, job_id: Optional[str] = None):
        self.enabled = enabled
        self.job_id = job_id or "offline"
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.doc_stats: Dict[str, Any] = {}
        self.element_counts: Counter = Counter()
        self.raw_block_count: int = 0
        self.triage_source: str = ""
        self.split_events: List[SplitEvent] = []
        self.merge_events: List[MergeEvent] = []
        self.chunk_records: List[ChunkForensicRecord] = []
        self.semantic_group_count: int = 0
        self.packed_chunk_count: int = 0
        self.section_count: int = 0
        self.consolidate_rounds: List[Dict[str, Any]] = []
        self.stage_timings: List[StageTiming] = []
        self.hierarchy_tree: Dict[str, Any] = {}
        self.routing_distribution: Dict[str, int] = {}
        self.config_snapshot: Dict[str, Any] = {}
        self.extras: Dict[str, Any] = {}
        self._event_i = 0
        self._pending_split_reason: Optional[str] = None
        self._pending_split_detail: str = ""

    def record_split(
        self,
        reason: str,
        *,
        detail: str = "",
        buffer_tokens_before: int = 0,
        incoming_tokens: int = 0,
        similarity: Optional[float] = None,
        section_title: Optional[str] = None,
        element_type: Optional[str] = None,
    ) -> None:
        if not self.enabled:
            return
        self._event_i += 1
        self.split_events.append(
            SplitEvent(
                event_index=self._event_i,
                reason=reason,
                detail=detail,
                buffer_tokens_before=buffer_tokens_before,
                incoming_tokens=incoming_tokens,
                similarity=similarity,
                section_title=section_title,
                element_type=element_type,
            )
        )
        self._pending_split_reason = reason
        self._pending_split_detail = detail

    def record_merge(
        self,
        reason: str,
        *,
        detail: str = "",
        chunks_merged: int = 0,
        tokens_before: int = 0,
        tokens_after: int = 0,
        similarity: Optional[float] = None,
        section_title: Optional[str] = None,
    ) -> None:
        if not self.enabled:
            return
        self.merge_events.append(
            MergeEvent(
                reason=reason,
                detail=detail,
                chunks_merged=chunks_merged,
                tokens_before=tokens_before,
                tokens_after=tokens_after,
                similarity=similarity,
                section_title=section_title,
            )
        )

    def take_pending_split_reason(self) -> tuple[Optional[str], str]:
        r, d = self._pending_split_reason, self._pending_split_detail
        self._pending_split_reason = None
        self._pending_split_detail = ""
        return r, d

    def add_timing(self, stage: str, ms: float, notes: str = "") -> None:
        if not self.enabled:
            return
        self.stage_timings.append(StageTiming(stage=stage, ms=ms, notes=notes))

    def split_reason_histogram(self) -> Dict[str, int]:
        return dict(Counter(e.reason for e in self.split_events))

    def token_stats(self) -> Dict[str, Any]:
        toks = [c.estimated_tokens for c in self.chunk_records]
        if not toks:
            return {}
        toks_sorted = sorted(toks)
        n = len(toks)

        def pct(threshold: int, mode: str = "under") -> float:
            if mode == "under":
                c = sum(1 for t in toks if t < threshold)
            elif mode == "above":
                c = sum(1 for t in toks if t > threshold)
            else:
                lo, hi = threshold  # type: ignore
                c = sum(1 for t in toks if lo <= t <= hi)
            return round(100.0 * c / n, 1)

        between_500_900 = round(100.0 * sum(1 for t in toks if 500 <= t <= 900) / n, 1)
        return {
            "count": n,
            "average": round(statistics.mean(toks), 1),
            "median": round(statistics.median(toks), 1),
            "min": min(toks),
            "max": max(toks),
            "stdev": round(statistics.pstdev(toks), 1) if n > 1 else 0.0,
            "percent_under_100": pct(100),
            "percent_under_250": pct(250),
            "percent_under_400": pct(400),
            "percent_between_500_900": between_500_900,
            "percent_above_1200": pct(1200, "above"),
            "histogram_buckets": _histogram(toks),
            "smallest_examples": _examples(self.chunk_records, smallest=True, k=5),
            "largest_examples": _examples(self.chunk_records, smallest=False, k=5),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "started_at": self.started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "doc_stats": self.doc_stats,
            "element_counts": dict(self.element_counts),
            "raw_block_count": self.raw_block_count,
            "triage_source": self.triage_source,
            "semantic_group_count": self.semantic_group_count,
            "packed_chunk_count": self.packed_chunk_count,
            "section_count": self.section_count,
            "split_reason_histogram": self.split_reason_histogram(),
            "split_events": [asdict(e) for e in self.split_events],
            "merge_events": [asdict(e) for e in self.merge_events],
            "consolidate_rounds": self.consolidate_rounds,
            "token_stats": self.token_stats(),
            "chunk_records": [asdict(c) for c in self.chunk_records],
            "stage_timings": [asdict(t) for t in self.stage_timings],
            "hierarchy_tree": self.hierarchy_tree,
            "routing_distribution": self.routing_distribution,
            "config_snapshot": self.config_snapshot,
            "extras": self.extras,
        }

    def save(self, path: str) -> str:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        return path


def _histogram(toks: Sequence[int]) -> Dict[str, int]:
    buckets = [
        ("0-99", 0, 99),
        ("100-249", 100, 249),
        ("250-399", 250, 399),
        ("400-499", 400, 499),
        ("500-900", 500, 900),
        ("901-1200", 901, 1200),
        ("1201+", 1201, 10**9),
    ]
    out: Dict[str, int] = {}
    for label, lo, hi in buckets:
        out[label] = sum(1 for t in toks if lo <= t <= hi)
    return out


def _examples(
    records: Sequence[ChunkForensicRecord], *, smallest: bool, k: int
) -> List[Dict[str, Any]]:
    ordered = sorted(records, key=lambda r: r.estimated_tokens, reverse=not smallest)
    out = []
    for r in ordered[:k]:
        out.append(
            {
                "chunk_index": r.chunk_index,
                "tokens": r.estimated_tokens,
                "section": r.section,
                "reason_split": r.reason_split,
                "preview": (r.content_preview or "")[:160],
            }
        )
    return out


def forensics_enabled_from_env() -> bool:
    return str(os.getenv("CHUNKING_FORENSICS", "")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def default_forensics_path(job_id: str) -> str:
    root = os.getenv("VECTOR_DB_PATH", "./local_db/aux")
    return os.path.join(root, "chunking_forensics", f"{job_id}.json")


class Timer:
    def __init__(self, forensics: Optional[ChunkingForensics], stage: str):
        self.forensics = forensics
        self.stage = stage
        self._t0 = 0.0

    def __enter__(self):
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *args):
        if self.forensics and self.forensics.enabled:
            ms = (time.perf_counter() - self._t0) * 1000.0
            self.forensics.add_timing(self.stage, ms)
