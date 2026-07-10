"""
Knowledge object schemas (Phase 2.F).

Document-scoped structured understanding — not free-form prose.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class EvidenceSpan:
    chunk_id: str
    quote: str
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EvidenceSpan":
        return cls(
            chunk_id=str(d.get("chunk_id") or ""),
            quote=str(d.get("quote") or ""),
            confidence=float(d.get("confidence") if d.get("confidence") is not None else 1.0),
        )


@dataclass
class Entity:
    id: str
    type: str
    name: str
    aliases: List[str] = field(default_factory=list)
    evidence: List[EvidenceSpan] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "aliases": list(self.aliases),
            "evidence": [e.to_dict() for e in self.evidence],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Entity":
        return cls(
            id=str(d.get("id") or d.get("name") or ""),
            type=str(d.get("type") or "Entity"),
            name=str(d.get("name") or ""),
            aliases=[str(a) for a in (d.get("aliases") or [])],
            evidence=[EvidenceSpan.from_dict(e) for e in (d.get("evidence") or d.get("spans") or []) if isinstance(e, dict)],
        )


@dataclass
class Concept:
    id: str
    label: str
    definition: str = ""
    evidence: List[EvidenceSpan] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "definition": self.definition,
            "evidence": [e.to_dict() for e in self.evidence],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Concept":
        return cls(
            id=str(d.get("id") or d.get("label") or ""),
            label=str(d.get("label") or ""),
            definition=str(d.get("definition") or ""),
            evidence=[EvidenceSpan.from_dict(e) for e in (d.get("evidence") or []) if isinstance(e, dict)],
        )


@dataclass
class Event:
    id: str
    name: str
    time: str = ""
    actors: List[str] = field(default_factory=list)
    evidence: List[EvidenceSpan] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "time": self.time,
            "actors": list(self.actors),
            "evidence": [e.to_dict() for e in self.evidence],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Event":
        return cls(
            id=str(d.get("id") or d.get("name") or ""),
            name=str(d.get("name") or ""),
            time=str(d.get("time") or ""),
            actors=[str(a) for a in (d.get("actors") or [])],
            evidence=[EvidenceSpan.from_dict(e) for e in (d.get("evidence") or []) if isinstance(e, dict)],
        )


@dataclass
class Topic:
    id: str
    label: str
    chunk_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Topic":
        return cls(
            id=str(d.get("id") or d.get("label") or ""),
            label=str(d.get("label") or ""),
            chunk_ids=[str(c) for c in (d.get("chunk_ids") or [])],
        )


@dataclass
class Citation:
    id: str
    raw: str
    resolved_to: Optional[str] = None
    evidence: List[EvidenceSpan] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "raw": self.raw,
            "resolved_to": self.resolved_to,
            "evidence": [e.to_dict() for e in self.evidence],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Citation":
        return cls(
            id=str(d.get("id") or ""),
            raw=str(d.get("raw") or ""),
            resolved_to=d.get("resolved_to"),
            evidence=[EvidenceSpan.from_dict(e) for e in (d.get("evidence") or []) if isinstance(e, dict)],
        )


@dataclass
class Relation:
    id: str
    src: str
    rel: str
    dst: str
    confidence: float = 0.5
    evidence: List[EvidenceSpan] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "src": self.src,
            "rel": self.rel,
            "dst": self.dst,
            "confidence": self.confidence,
            "evidence": [e.to_dict() for e in self.evidence],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Relation":
        return cls(
            id=str(d.get("id") or f"{d.get('src')}_{d.get('rel')}_{d.get('dst')}"),
            src=str(d.get("src") or ""),
            rel=str(d.get("rel") or "RELATES_TO"),
            dst=str(d.get("dst") or ""),
            confidence=float(d.get("confidence") if d.get("confidence") is not None else 0.5),
            evidence=[EvidenceSpan.from_dict(e) for e in (d.get("evidence") or []) if isinstance(e, dict)],
        )


@dataclass
class KnowledgeDocument:
    document_id: str
    status: str = "done"  # pending|done|failed|skipped
    entities: List[Entity] = field(default_factory=list)
    concepts: List[Concept] = field(default_factory=list)
    events: List[Event] = field(default_factory=list)
    topics: List[Topic] = field(default_factory=list)
    citations: List[Citation] = field(default_factory=list)
    relations: List[Relation] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "status": self.status,
            "entities": [e.to_dict() for e in self.entities],
            "concepts": [c.to_dict() for c in self.concepts],
            "events": [e.to_dict() for e in self.events],
            "topics": [t.to_dict() for t in self.topics],
            "citations": [c.to_dict() for c in self.citations],
            "relations": [r.to_dict() for r in self.relations],
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "KnowledgeDocument":
        return cls(
            document_id=str(d.get("document_id") or ""),
            status=str(d.get("status") or "done"),
            entities=[Entity.from_dict(x) for x in (d.get("entities") or []) if isinstance(x, dict)],
            concepts=[Concept.from_dict(x) for x in (d.get("concepts") or []) if isinstance(x, dict)],
            events=[Event.from_dict(x) for x in (d.get("events") or []) if isinstance(x, dict)],
            topics=[Topic.from_dict(x) for x in (d.get("topics") or []) if isinstance(x, dict)],
            citations=[Citation.from_dict(x) for x in (d.get("citations") or []) if isinstance(x, dict)],
            relations=[Relation.from_dict(x) for x in (d.get("relations") or []) if isinstance(x, dict)],
            meta=dict(d.get("meta") or {}),
        )

    def merge(self, other: "KnowledgeDocument") -> "KnowledgeDocument":
        """Merge another batch into this document (by id, prefer longer evidence)."""
        def _merge_list(existing, incoming, key_fn):
            by_id = {key_fn(x): x for x in existing}
            for item in incoming:
                k = key_fn(item)
                if k not in by_id:
                    by_id[k] = item
                else:
                    # keep the one with more evidence
                    cur = by_id[k]
                    cur_ev = getattr(cur, "evidence", None)
                    new_ev = getattr(item, "evidence", None)
                    if new_ev is not None and (cur_ev is None or len(new_ev) > len(cur_ev)):
                        by_id[k] = item
            return list(by_id.values())

        return KnowledgeDocument(
            document_id=self.document_id or other.document_id,
            status=other.status or self.status,
            entities=_merge_list(self.entities, other.entities, lambda e: e.id),
            concepts=_merge_list(self.concepts, other.concepts, lambda e: e.id),
            events=_merge_list(self.events, other.events, lambda e: e.id),
            topics=_merge_list(self.topics, other.topics, lambda e: e.id),
            citations=_merge_list(self.citations, other.citations, lambda e: e.id),
            relations=_merge_list(self.relations, other.relations, lambda e: e.id),
            meta={**self.meta, **other.meta},
        )


def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse/repair LLM JSON: strip fences, find outermost object.
    Returns dict or None.
    """
    if not text:
        return None
    s = text.strip()
    # Strip markdown fences
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", s, re.I)
    if fence:
        s = fence.group(1).strip()
    # Find first { ... last }
    start = s.find("{")
    end = s.rfind("}")
    if start < 0 or end <= start:
        return None
    blob = s[start : end + 1]
    try:
        data = json.loads(blob)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        # Light repair: trailing commas
        repaired = re.sub(r",\s*}", "}", blob)
        repaired = re.sub(r",\s*]", "]", repaired)
        try:
            data = json.loads(repaired)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None


def knowledge_from_extraction(
    document_id: str,
    data: Dict[str, Any],
    *,
    status: str = "done",
) -> KnowledgeDocument:
    """Build KnowledgeDocument from a raw extraction dict."""
    payload = dict(data)
    payload["document_id"] = document_id
    payload["status"] = status
    return KnowledgeDocument.from_dict(payload)
