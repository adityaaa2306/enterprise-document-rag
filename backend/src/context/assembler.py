"""
ContextAssembler — pack retrieved passages under a token budget (Phase 2.C).

Not an agent: deterministic dedupe → sibling merge → section order → budget pack.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Union

from src.chunking.service import estimate_tokens
from src.core.config import settings

log = logging.getLogger(__name__)


@dataclass
class ProvenanceEntry:
    chunk_id: str
    rank: int
    score: float
    parent_id: Optional[str] = None
    section_path: Optional[str] = None
    citation: int = 0


@dataclass
class PackedPassage:
    content: str
    chunk_ids: List[str]
    score: float = 0.0
    rank: int = 0
    parent_id: Optional[str] = None
    section_path: Optional[str] = None
    citation: int = 0


@dataclass
class ContextPack:
    """LLM-ready context with provenance for explainability / 2.D."""

    context_text: str
    passages: List[PackedPassage] = field(default_factory=list)
    provenance: Dict[str, ProvenanceEntry] = field(default_factory=dict)
    tokens_used: int = 0
    tokens_budget: int = 0
    stats: Dict[str, Any] = field(default_factory=dict)

    @property
    def source_texts(self) -> List[str]:
        """Compatible with RagQueryResponse.sources."""
        return [p.content for p in self.passages]


@dataclass
class _NormPassage:
    chunk_id: str
    content: str
    score: float
    rank: int
    parent_id: Optional[str]
    section_path: Optional[str]


def _lexical_overlap(a: str, b: str) -> float:
    ta = set(re.findall(r"[a-zA-Z0-9_]{3,}", (a or "").lower()))
    tb = set(re.findall(r"[a-zA-Z0-9_]{3,}", (b or "").lower()))
    if not ta or not tb:
        # Near-identical short strings
        sa, sb = (a or "").strip().lower(), (b or "").strip().lower()
        if sa and sa == sb:
            return 1.0
        return 0.0
    return len(ta & tb) / max(1, len(ta | tb))


def _normalize(passages: Sequence[Any]) -> List[_NormPassage]:
    out: List[_NormPassage] = []
    for i, p in enumerate(passages):
        if isinstance(p, dict):
            content = p.get("content") or p.get("text") or ""
            chunk_id = str(p.get("chunk_id") or p.get("id") or f"anon_{i}")
            score = float(p.get("score") or 0.0)
            rank = int(p.get("rank") if p.get("rank") is not None else i)
            parent_id = p.get("parent_id")
            section_path = p.get("section_path")
        else:
            content = getattr(p, "content", "") or getattr(p, "text", "") or ""
            chunk_id = str(getattr(p, "chunk_id", None) or getattr(p, "id", None) or f"anon_{i}")
            score = float(getattr(p, "score", 0.0) or 0.0)
            rank = int(getattr(p, "rank", i) if getattr(p, "rank", None) is not None else i)
            parent_id = getattr(p, "parent_id", None)
            section_path = getattr(p, "section_path", None)
            meta = getattr(p, "meta", None) or {}
            if isinstance(meta, dict):
                parent_id = parent_id or meta.get("parent_id")
                section_path = section_path or meta.get("section_path")
                if score == 0.0 and meta.get("score") is not None:
                    score = float(meta["score"])
        if not content:
            continue
        out.append(
            _NormPassage(
                chunk_id=chunk_id,
                content=content,
                score=score,
                rank=rank,
                parent_id=parent_id,
                section_path=section_path,
            )
        )
    return out


def budget_for_tier(tier: Optional[str] = None) -> int:
    t = (tier or "heavy").lower()
    if t == "light":
        return int(settings.CONTEXT_TOKEN_BUDGET_LIGHT)
    if t == "medium":
        return int(settings.CONTEXT_TOKEN_BUDGET_MEDIUM)
    return int(settings.CONTEXT_TOKEN_BUDGET_HEAVY)


class ContextAssembler:
    """
    Pack ranked passages into a ContextPack.

    Pipeline: normalize → dedupe → sibling merge → budget select → section order → format.
    """

    def __init__(
        self,
        dedup_threshold: Optional[float] = None,
        token_budget: Optional[int] = None,
    ):
        self.dedup_threshold = (
            dedup_threshold
            if dedup_threshold is not None
            else float(settings.CONTEXT_DEDUP_THRESHOLD)
        )
        self.token_budget = token_budget

    def pack(
        self,
        passages: Sequence[Any],
        *,
        tier: str = "heavy",
        query: Optional[str] = None,
    ) -> ContextPack:
        import time

        from src.monitoring.query_latency import STAGE_CONTEXT_ASSEMBLE

        t0 = time.perf_counter()
        budget = self.token_budget if self.token_budget is not None else budget_for_tier(tier)
        # Cap chat/RAG context so generation prompts stay lean (retrieval unchanged)
        response_cap = int(getattr(settings, "RESPONSE_CONTEXT_BUDGET", 0) or 0)
        if response_cap > 0:
            budget = min(budget, response_cap)
        norms = _normalize(passages)
        if not norms:
            assemble_ms = round((time.perf_counter() - t0) * 1000.0, 3)
            return ContextPack(
                context_text="",
                tokens_used=0,
                tokens_budget=budget,
                stats={
                    "input": 0,
                    "after_dedupe": 0,
                    "after_merge": 0,
                    "packed": 0,
                    "latency_ms": {STAGE_CONTEXT_ASSEMBLE: assemble_ms},
                },
            )

        after_dedupe = self._dedupe(norms)
        after_merge = self._merge_siblings(after_dedupe)
        selected = self._select_under_budget(after_merge, budget)
        ordered = self._order_by_section(selected)

        packed: List[PackedPassage] = []
        provenance: Dict[str, ProvenanceEntry] = {}
        for i, item in enumerate(ordered, start=1):
            pp = PackedPassage(
                content=item["content"],
                chunk_ids=list(item["chunk_ids"]),
                score=item["score"],
                rank=item["rank"],
                parent_id=item.get("parent_id"),
                section_path=item.get("section_path"),
                citation=i,
            )
            packed.append(pp)
            for cid in pp.chunk_ids:
                provenance[cid] = ProvenanceEntry(
                    chunk_id=cid,
                    rank=pp.rank,
                    score=pp.score,
                    parent_id=pp.parent_id,
                    section_path=pp.section_path,
                    citation=i,
                )

        context_text = self._format(packed)
        tokens_used = estimate_tokens(context_text)
        assemble_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        return ContextPack(
            context_text=context_text,
            passages=packed,
            provenance=provenance,
            tokens_used=tokens_used,
            tokens_budget=budget,
            stats={
                "input": len(norms),
                "after_dedupe": len(after_dedupe),
                "after_merge": len(after_merge),
                "packed": len(packed),
                "tier": tier,
                "query_len": len(query or ""),
                "latency_ms": {STAGE_CONTEXT_ASSEMBLE: assemble_ms},
            },
        )

    def _dedupe(self, passages: List[_NormPassage]) -> List[_NormPassage]:
        # Prefer higher score; stable by original rank
        ordered = sorted(passages, key=lambda p: (-p.score, p.rank))
        kept: List[_NormPassage] = []
        for p in ordered:
            dup = False
            for k in kept:
                if _lexical_overlap(p.content, k.content) >= self.dedup_threshold:
                    dup = True
                    break
                # Exact / near-exact string match
                if p.content.strip() == k.content.strip():
                    dup = True
                    break
            if not dup:
                kept.append(p)
        # Restore retrieval-ish order for merge
        kept.sort(key=lambda p: p.rank)
        return kept

    def _merge_siblings(self, passages: List[_NormPassage]) -> List[Dict[str, Any]]:
        """Merge passages that share the same parent_id into one block."""
        if not passages:
            return []

        # Group by parent_id (None → each alone)
        groups: Dict[str, List[_NormPassage]] = {}
        singles: List[_NormPassage] = []
        order_keys: List[str] = []

        for p in passages:
            if not p.parent_id:
                key = f"__solo__{p.chunk_id}"
                singles.append(p)
                groups[key] = [p]
                order_keys.append(key)
            else:
                key = f"__parent__{p.parent_id}"
                if key not in groups:
                    groups[key] = []
                    order_keys.append(key)
                groups[key].append(p)

        merged: List[Dict[str, Any]] = []
        seen = set()
        for key in order_keys:
            if key in seen:
                continue
            seen.add(key)
            members = groups[key]
            # Sort siblings by section_path / rank
            members = sorted(
                members,
                key=lambda m: (m.section_path or "", m.rank),
            )
            content = "\n\n".join(m.content for m in members)
            merged.append(
                {
                    "content": content,
                    "chunk_ids": [m.chunk_id for m in members],
                    "score": max(m.score for m in members),
                    "rank": min(m.rank for m in members),
                    "parent_id": members[0].parent_id,
                    "section_path": members[0].section_path,
                }
            )
        return merged

    def _select_under_budget(
        self, items: List[Dict[str, Any]], budget: int
    ) -> List[Dict[str, Any]]:
        # Greedy by score; always try to keep at least one
        by_score = sorted(items, key=lambda x: (-x["score"], x["rank"]))
        selected: List[Dict[str, Any]] = []
        used = 0
        # Reserve small overhead for citation markers / separators
        overhead_per = 8
        for item in by_score:
            cost = estimate_tokens(item["content"]) + overhead_per
            if selected and used + cost > budget:
                continue
            if not selected and cost > budget:
                # Truncate single oversized passage
                max_chars = max(64, budget * 4)
                truncated = dict(item)
                truncated["content"] = item["content"][:max_chars]
                selected.append(truncated)
                used = estimate_tokens(truncated["content"])
                break
            selected.append(item)
            used += cost
        return selected

    def _order_by_section(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return sorted(
            items,
            key=lambda x: (
                x.get("section_path") is None,
                x.get("section_path") or "",
                x.get("rank", 0),
            ),
        )

    def _format(self, packed: List[PackedPassage]) -> str:
        # Lean headers: citation index only (section path kept in provenance for UI)
        blocks: List[str] = []
        for p in packed:
            blocks.append(f"[{p.citation}]\n{p.content}")
        return "\n\n---\n\n".join(blocks)


def assemble_context(
    passages: Sequence[Any],
    *,
    tier: str = "heavy",
    query: Optional[str] = None,
) -> ContextPack:
    """Convenience wrapper."""
    return ContextAssembler().pack(passages, tier=tier, query=query)
