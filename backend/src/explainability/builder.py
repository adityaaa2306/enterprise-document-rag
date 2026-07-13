"""
ExplainabilityBuilder — AnswerEnvelope metadata (Phase 2.H).

Library (not an agent): wraps Response Agent outputs with provenance fields.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from src.context.assembler import ContextPack
from src.core.config import settings

log = logging.getLogger(__name__)


@dataclass
class RetrievedChunkRef:
    id: str
    score: float = 0.0
    parent_section: Optional[str] = None
    citation: Optional[int] = None
    preview: Optional[str] = None
    rank: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ModelRef:
    tier: str
    model_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AnswerEnvelope:
    """Enterprise-shaped answer metadata (optional fields on /rag-query)."""

    answer: str
    confidence: float = 0.0
    knowledge_sources: List[str] = field(default_factory=list)
    retrieved_chunks: List[RetrievedChunkRef] = field(default_factory=list)
    entities_used: List[str] = field(default_factory=list)
    reasoning_path: List[str] = field(default_factory=list)
    missing_context: List[str] = field(default_factory=list)
    model: Optional[ModelRef] = None
    routing_ref: Optional[str] = None
    skill: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "answer": self.answer,
            "confidence": self.confidence,
            "knowledge_sources": list(self.knowledge_sources),
            "retrieved_chunks": [c.to_dict() for c in self.retrieved_chunks],
            "entities_used": list(self.entities_used),
            "reasoning_path": list(self.reasoning_path),
            "missing_context": list(self.missing_context),
            "model": self.model.to_dict() if self.model else None,
            "routing_ref": self.routing_ref,
            "skill": self.skill,
        }


class ExplainabilityBuilder:
    def build(
        self,
        *,
        answer: str,
        query: str,
        document_id: str,
        pack: Optional[ContextPack] = None,
        skill: Optional[str] = None,
        model_used: Optional[str] = None,
        tier: str = "heavy",
        routing_decision: Optional[Dict[str, Any]] = None,
        retrieval_debug: Optional[Dict[str, Any]] = None,
        prior_entities: Optional[Sequence[str]] = None,
        response_debug: Optional[Dict[str, Any]] = None,
    ) -> AnswerEnvelope:
        retrieval_debug = retrieval_debug or {}
        response_debug = response_debug or {}

        retrieved = self._retrieved_chunks(pack)
        entities = self._entities_used(document_id, query, prior_entities)
        path = self._reasoning_path(retrieval_debug, pack, skill)
        missing = self._missing_context(answer, pack, retrieved, entities, query)
        confidence = self._confidence(answer, pack, retrieved, missing)
        sources = self._knowledge_sources(document_id, retrieved, entities)
        routing_ref = self._routing_ref(document_id, routing_decision)

        return AnswerEnvelope(
            answer=answer,
            confidence=confidence,
            knowledge_sources=sources,
            retrieved_chunks=retrieved,
            entities_used=entities,
            reasoning_path=path,
            missing_context=missing,
            model=ModelRef(tier=tier, model_id=model_used),
            routing_ref=routing_ref,
            skill=skill,
        )

    def _retrieved_chunks(self, pack: Optional[ContextPack]) -> List[RetrievedChunkRef]:
        """One explainability row per packed passage (not per merged chunk_id)."""
        if not pack:
            return []
        passages = list(pack.passages or [])
        out: List[RetrievedChunkRef] = []
        for i, p in enumerate(passages):
            ids = [cid for cid in (p.chunk_ids or []) if cid]
            primary_id = ids[0] if ids else f"passage_{p.citation or i + 1}"
            preview = (p.content or "").strip()
            if len(preview) > 280:
                preview = preview[:277].rstrip() + "…"
            out.append(
                RetrievedChunkRef(
                    id=primary_id,
                    score=self._display_relevance(float(p.score or 0.0), i, len(passages)),
                    parent_section=self._section_label(p.section_path, p.content),
                    citation=p.citation if p.citation is not None else i + 1,
                    preview=preview or None,
                    rank=i,
                )
            )
        return out

    @staticmethod
    def _section_label(section_path: Optional[str], content: Optional[str]) -> Optional[str]:
        raw = (section_path or "").strip()
        if raw and raw.lower() not in ("(preamble)", "preamble"):
            return raw
        # Derive a readable label from the passage when PDF triage left everything as preamble
        text = (content or "").strip()
        if not text:
            return "Document"
        for line in text.splitlines():
            line = line.strip()
            if len(line) >= 8:
                return line[:120] + ("…" if len(line) > 120 else "")
        return text[:120] + ("…" if len(text) > 120 else "")

    @staticmethod
    def _display_relevance(raw_score: float, rank: int, total: int) -> float:
        """
        Map retrieval scores to a UI-friendly 0–1 relevance.
        Hybrid RRF scores are ~0.01–0.05; parent_expand often 0.0 — those are not
        cosine similarities and must not be compared to 0.45/0.75 thresholds as-is.
        """
        if raw_score >= 0.15:
            return max(0.0, min(1.0, round(raw_score, 4)))
        # Rank-based fallback for RRF / zero scores (top passage ≈ High)
        if total <= 1:
            return 0.88
        return round(max(0.42, 0.95 - (0.12 * rank)), 4)

    def _entities_used(
        self,
        document_id: str,
        query: str,
        prior_entities: Optional[Sequence[str]],
    ) -> List[str]:
        found: List[str] = []
        try:
            from src.knowledge.graph_store import GraphStore

            matched = GraphStore().match_entity_ids(document_id, query)
            for e in matched:
                if e not in found:
                    found.append(e)
        except Exception as e:
            log.debug(f"Entity match skipped: {e}")

        for e in prior_entities or []:
            if e and e not in found:
                found.append(e)
        return found

    def _reasoning_path(
        self,
        retrieval_debug: Dict[str, Any],
        pack: Optional[ContextPack],
        skill: Optional[str],
    ) -> List[str]:
        path = ["retrieve"]
        mode = retrieval_debug.get("mode")
        if mode:
            path.append(f"retrieve:{mode}")
        if retrieval_debug.get("graph_seed") or retrieval_debug.get("seed_ids"):
            path.append("graph_seed")
        if settings.ENABLE_PARENT_EXPAND:
            path.append("expand_parent")
        if pack is not None and settings.USE_CONTEXT_ASSEMBLER:
            path.append("context_pack")
        if skill:
            path.append(f"skill:{skill}")
        else:
            path.append("generate")
        if settings.EXPLAINABILITY_ENABLED:
            path.append("explain")
        return path

    def _missing_context(
        self,
        answer: str,
        pack: Optional[ContextPack],
        retrieved: List[RetrievedChunkRef],
        entities: List[str],
        query: str,
    ) -> List[str]:
        gaps: List[str] = []
        low = (answer or "").lower()
        if any(x in low for x in ("insufficient", "not enough context", "no relevant", "cannot find", "don't know")):
            gaps.append("model_reported_insufficient_context")
        if not retrieved:
            gaps.append("no_retrieved_chunks")
        if pack and pack.tokens_budget and pack.tokens_used >= pack.tokens_budget * 0.95:
            gaps.append("context_token_budget_saturated")
        # Entity-looking query but no graph hits
        if len(query.split()) <= 12 and any(c.isupper() for c in query) and not entities:
            # soft signal only when graph likely empty
            pass
        return gaps

    def _confidence(
        self,
        answer: str,
        pack: Optional[ContextPack],
        retrieved: List[RetrievedChunkRef],
        missing: List[str],
    ) -> float:
        if not answer or answer.startswith("Error:") or answer.startswith("Failed"):
            return 0.15
        base = 0.45
        if retrieved:
            base += min(0.25, 0.08 * len(retrieved))
            avg_rel = sum(float(c.score or 0.0) for c in retrieved) / max(len(retrieved), 1)
            base += min(0.20, avg_rel * 0.22)
        if pack and pack.stats.get("packed"):
            base += 0.08
        if missing:
            base -= 0.08 * len(missing)
        return max(0.0, min(1.0, round(base, 3)))

    def _knowledge_sources(
        self,
        document_id: str,
        retrieved: List[RetrievedChunkRef],
        entities: List[str],
    ) -> List[str]:
        sources = [document_id]
        for c in retrieved:
            if c.id not in sources:
                sources.append(c.id)
        for e in entities:
            node = f"node:{e}"
            if node not in sources:
                sources.append(node)
        return sources

    def _routing_ref(
        self,
        document_id: str,
        routing_decision: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        if not routing_decision:
            return None
        # Stable ref: document + selected model + policy version
        model = routing_decision.get("selected_model") or routing_decision.get("compile_fallbacks", [None])[0]
        policy = routing_decision.get("policy_version") or settings.CRE_POLICY_VERSION
        return f"{document_id}:{policy}:{model}"


def build_envelope(**kwargs: Any) -> AnswerEnvelope:
    return ExplainabilityBuilder().build(**kwargs)
