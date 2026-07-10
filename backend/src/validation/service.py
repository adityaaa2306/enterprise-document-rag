"""
ValidationService — QVA facade + knowledge grounding (Phase 2.F).

Not an agent: extends Phase-1 quality checks with evidence-span grounding.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set

from src.agents import quality_validation
from src.knowledge.schemas import (
    Citation,
    Concept,
    Entity,
    Event,
    EvidenceSpan,
    KnowledgeDocument,
    Relation,
    Topic,
)

log = logging.getLogger(__name__)


@dataclass
class GroundingReport:
    kept_entities: int = 0
    dropped_entities: int = 0
    kept_concepts: int = 0
    dropped_concepts: int = 0
    kept_events: int = 0
    dropped_events: int = 0
    kept_citations: int = 0
    dropped_citations: int = 0
    kept_relations: int = 0
    dropped_relations: int = 0
    kept_topics: int = 0
    dropped_topics: int = 0
    details: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kept_entities": self.kept_entities,
            "dropped_entities": self.dropped_entities,
            "kept_concepts": self.kept_concepts,
            "dropped_concepts": self.dropped_concepts,
            "kept_events": self.kept_events,
            "dropped_events": self.dropped_events,
            "kept_citations": self.kept_citations,
            "dropped_citations": self.dropped_citations,
            "kept_relations": self.kept_relations,
            "dropped_relations": self.dropped_relations,
            "kept_topics": self.kept_topics,
            "dropped_topics": self.dropped_topics,
            "details": list(self.details),
        }


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def quote_grounded_in_chunk(quote: str, chunk_text: str, min_overlap: float = 0.55) -> bool:
    """True if quote is a substring of chunk or has high token overlap."""
    q = _norm(quote)
    c = _norm(chunk_text)
    if not q or not c:
        return False
    if q in c:
        return True
    # Allow short exact name mentions (≥3 chars) as grounded if present
    if len(q) >= 3 and q in c:
        return True
    qt = set(re.findall(r"[a-z0-9_]{3,}", q))
    ct = set(re.findall(r"[a-z0-9_]{3,}", c))
    if not qt:
        return False
    return (len(qt & ct) / max(len(qt), 1)) >= min_overlap


def evidence_is_grounded(
    evidence: Sequence[EvidenceSpan],
    chunk_texts: Dict[str, str],
) -> bool:
    """Require ≥1 evidence span with known chunk_id and grounded quote."""
    for ev in evidence:
        if not ev.chunk_id or not ev.quote:
            continue
        text = chunk_texts.get(ev.chunk_id)
        if text is None:
            continue
        if quote_grounded_in_chunk(ev.quote, text):
            return True
    return False


class ValidationService:
    """Wraps QVA + knowledge grounding."""

    def validate_chunks(self, chunks: List[Any], summaries: List[str]):
        return quality_validation.validate_chunks(chunks, summaries)

    def validate_final(self, source_summaries: List[str], final_summary: str):
        return quality_validation.validate_final(source_summaries, final_summary)

    def ground_knowledge(
        self,
        doc: KnowledgeDocument,
        chunk_texts: Dict[str, str],
    ) -> tuple[KnowledgeDocument, GroundingReport]:
        """
        Drop ungrounded nodes. Every persisted entity/concept/event/citation
        must have ≥1 evidence (chunk_id + quote) grounded in chunk text.
        Relations kept only if both endpoints survive. Topics filtered to known chunks.
        """
        report = GroundingReport()
        known_ids: Set[str] = set()

        entities: List[Entity] = []
        for e in doc.entities:
            if e.name and evidence_is_grounded(e.evidence, chunk_texts):
                entities.append(e)
                known_ids.add(e.id)
                report.kept_entities += 1
            else:
                report.dropped_entities += 1
                report.details.append(f"drop entity {e.id or e.name}")

        concepts: List[Concept] = []
        for c in doc.concepts:
            if c.label and evidence_is_grounded(c.evidence, chunk_texts):
                concepts.append(c)
                known_ids.add(c.id)
                report.kept_concepts += 1
            else:
                report.dropped_concepts += 1
                report.details.append(f"drop concept {c.id or c.label}")

        events: List[Event] = []
        for ev in doc.events:
            if ev.name and evidence_is_grounded(ev.evidence, chunk_texts):
                events.append(ev)
                known_ids.add(ev.id)
                report.kept_events += 1
            else:
                report.dropped_events += 1
                report.details.append(f"drop event {ev.id or ev.name}")

        citations: List[Citation] = []
        for cit in doc.citations:
            if cit.raw and evidence_is_grounded(cit.evidence, chunk_texts):
                citations.append(cit)
                known_ids.add(cit.id)
                report.kept_citations += 1
            else:
                report.dropped_citations += 1
                report.details.append(f"drop citation {cit.id}")

        topics: List[Topic] = []
        for t in doc.topics:
            valid_chunks = [cid for cid in t.chunk_ids if cid in chunk_texts]
            if t.label and valid_chunks:
                topics.append(Topic(id=t.id, label=t.label, chunk_ids=valid_chunks))
                report.kept_topics += 1
            else:
                report.dropped_topics += 1

        relations: List[Relation] = []
        for r in doc.relations:
            if r.src in known_ids and r.dst in known_ids and r.src and r.dst:
                relations.append(r)
                report.kept_relations += 1
            else:
                report.dropped_relations += 1
                report.details.append(f"drop relation {r.id}")

        grounded = KnowledgeDocument(
            document_id=doc.document_id,
            status=doc.status,
            entities=entities,
            concepts=concepts,
            events=events,
            topics=topics,
            citations=citations,
            relations=relations,
            meta={
                **doc.meta,
                "grounding": report.to_dict(),
            },
        )
        return grounded, report
