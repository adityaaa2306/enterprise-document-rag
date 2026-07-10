"""
Understanding Agent — ingest-time cognition (Phase 2.F).

The only ingest agent: structured extraction over chunks using map-tier
model chain from RoutingDecision. Grounding is ValidationService (not an agent).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from src.agents import models
from src.core.config import settings
from src.knowledge.schemas import (
    KnowledgeDocument,
    extract_json_object,
    knowledge_from_extraction,
)
from src.validation.service import ValidationService

log = logging.getLogger(__name__)

_EXTRACT_SYSTEM = (
    "You extract structured knowledge from document chunks. "
    "Respond with a single JSON object only — no markdown, no prose. "
    "Every entity, concept, event, and citation MUST include evidence with "
    "chunk_id and a short verbatim quote from that chunk."
)

_EXTRACT_SCHEMA_HINT = """
Return JSON with this shape:
{
  "entities": [{"id","type","name","aliases":[],"evidence":[{"chunk_id","quote"}]}],
  "concepts": [{"id","label","definition","evidence":[{"chunk_id","quote"}]}],
  "events": [{"id","name","time","actors":[],"evidence":[{"chunk_id","quote"}]}],
  "topics": [{"id","label","chunk_ids":[]}],
  "citations": [{"id","raw","resolved_to","evidence":[{"chunk_id","quote"}]}],
  "relations": [{"id","src","rel","dst","confidence","evidence":[{"chunk_id","quote"}]}]
}
Use only chunk_ids provided. Quotes must be substrings of the chunk text.
rel examples: RELATES_TO, PART_OF, CITES, OCCURS_IN, DEFINED_AS, FOLLOWS.
""".strip()


@dataclass
class UnderstandingResult:
    document: KnowledgeDocument
    model_used: Optional[str] = None
    batches: int = 0
    raw_batches_ok: int = 0
    debug: Dict[str, Any] = field(default_factory=dict)


def _map_model_chain(routing_decision: Optional[Dict[str, Any]]) -> tuple[List[str], str]:
    """Prefer map-tier fallbacks from RoutingDecision; else light models."""
    if routing_decision:
        chain = list(routing_decision.get("fallbacks") or [])
        selected = routing_decision.get("selected_model")
        if selected and selected not in chain:
            chain = [selected] + chain
        tier = str(routing_decision.get("tier") or "light")
        if chain:
            # Safety: append light models
            for m in settings.light_models():
                if m not in chain:
                    chain.append(m)
            return chain, tier
    return list(settings.light_models()), "light"


def _format_chunk_batch(chunks: Sequence[Dict[str, str]]) -> str:
    blocks = []
    for c in chunks:
        blocks.append(f"[chunk_id={c['chunk_id']}]\n{c['text']}")
    return "\n\n".join(blocks)


class UnderstandingAgent:
    """Batch extract → merge → ground via ValidationService."""

    def __init__(self, validation: Optional[ValidationService] = None):
        self.validation = validation or ValidationService()

    def extract(
        self,
        document_id: str,
        chunks: Sequence[Any],
        *,
        routing_decision: Optional[Dict[str, Any]] = None,
        max_chunks_per_call: Optional[int] = None,
    ) -> UnderstandingResult:
        if not settings.ENABLE_UNDERSTANDING:
            empty = KnowledgeDocument(document_id=document_id, status="skipped")
            return UnderstandingResult(document=empty, debug={"disabled": True})

        batch_size = max_chunks_per_call or settings.UNDERSTANDING_MAX_CHUNKS_PER_CALL
        normalized = self._normalize_chunks(document_id, chunks)
        if not normalized:
            doc = KnowledgeDocument(document_id=document_id, status="done", meta={"empty_chunks": True})
            return UnderstandingResult(document=doc, debug={"empty": True})

        model_ids, tier = _map_model_chain(routing_decision)
        chunk_texts = {c["chunk_id"]: c["text"] for c in normalized}

        merged = KnowledgeDocument(document_id=document_id, status="done")
        model_used: Optional[str] = None
        batches = 0
        ok = 0

        for i in range(0, len(normalized), batch_size):
            batch = normalized[i : i + batch_size]
            batches += 1
            raw = self._call_extract(batch, model_ids, tier)
            if raw is None:
                continue
            text, used = raw
            if used:
                model_used = used
            data = extract_json_object(text)
            if not data:
                log.warning(f"Understanding batch {batches}: JSON parse failed")
                continue
            part = knowledge_from_extraction(document_id, data, status="done")
            merged = merged.merge(part)
            ok += 1

        grounded, report = self.validation.ground_knowledge(merged, chunk_texts)
        grounded.status = "done"
        grounded.meta = {
            **grounded.meta,
            "tier": tier,
            "model_used": model_used,
            "batches": batches,
            "batches_ok": ok,
            "input_chunks": len(normalized),
        }
        log.info(
            f"UnderstandingAgent doc={document_id}: entities={len(grounded.entities)} "
            f"relations={len(grounded.relations)} dropped_entities={report.dropped_entities} "
            f"model={model_used}"
        )
        return UnderstandingResult(
            document=grounded,
            model_used=model_used,
            batches=batches,
            raw_batches_ok=ok,
            debug={"grounding": report.to_dict(), "tier": tier},
        )

    def _normalize_chunks(self, document_id: str, chunks: Sequence[Any]) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []
        for i, c in enumerate(chunks):
            if isinstance(c, dict):
                text = c.get("text") or c.get("content") or ""
                idx = c.get("index", i)
                cid = c.get("chunk_id") or c.get("id") or f"{document_id}_{idx}"
            else:
                text = getattr(c, "content", "") or getattr(c, "text", "") or ""
                cid = getattr(c, "chunk_id", None) or getattr(c, "id", None) or f"{document_id}_{i}"
            if not text or not str(text).strip():
                continue
            # Cap very long chunks for prompt size
            t = str(text)
            if len(t) > 4000:
                t = t[:4000]
            out.append({"chunk_id": str(cid), "text": t})
        return out

    def _call_extract(
        self,
        batch: List[Dict[str, str]],
        model_ids: List[str],
        tier: str,
    ) -> Optional[tuple[str, Optional[str]]]:
        if models.get_nim_client() is None:
            log.warning("UnderstandingAgent: NIM client missing")
            return None
        user = (
            f"{_EXTRACT_SCHEMA_HINT}\n\nCHUNKS:\n{_format_chunk_batch(batch)}\n\nJSON:"
        )
        try:
            text, used = models.call_chat_with_fallback(
                model_ids,
                [
                    {"role": "system", "content": _EXTRACT_SYSTEM},
                    {"role": "user", "content": user},
                ],
                temperature=0.1,
                max_tokens=settings.UNDERSTANDING_MAX_TOKENS,
            )
            return text, used
        except Exception as e:
            log.error(f"Understanding extract call failed: {e}")
            return None


def run_understanding_for_document(document_id: str, job_id: Optional[str] = None) -> UnderstandingResult:
    """
    Load chunks + routing from storage, extract, persist knowledge_json.
    Updates JOB_STATUSES[job_id].understanding when job_id provided.
    """
    from src.memory import storage
    from src.db import jobs as job_store

    def _set_status(value: str) -> None:
        jid = job_id or document_id
        job_store.set_understanding(jid, value)

    if not settings.ENABLE_UNDERSTANDING:
        _set_status("skipped")
        empty = KnowledgeDocument(document_id=document_id, status="skipped")
        storage.save_knowledge(document_id, empty)
        return UnderstandingResult(document=empty, debug={"disabled": True})

    _set_status("pending")
    try:
        rows = storage.retrieve_chunks(document_id)
        chunks = [
            {"chunk_id": f"{document_id}_{r['index']}", "text": r["text"], "index": r["index"]}
            for r in rows
        ]
        routing = storage.get_routing_decision(document_id)
        result = UnderstandingAgent().extract(
            document_id,
            chunks,
            routing_decision=routing,
        )
        storage.save_knowledge(document_id, result.document)
        try:
            from src.knowledge.graph_store import sync_graph_from_knowledge

            sync_graph_from_knowledge(document_id, result.document)
        except Exception as ge:
            log.warning(f"Graph sync failed for {document_id}: {ge}")
        _set_status("done" if result.document.status != "failed" else "failed")
        return result
    except Exception as e:
        log.error(f"Understanding job failed for {document_id}: {e}")
        failed = KnowledgeDocument(
            document_id=document_id,
            status="failed",
            meta={"error": str(e)},
        )
        try:
            storage.save_knowledge(document_id, failed)
        except Exception:
            pass
        _set_status("failed")
        return UnderstandingResult(document=failed, debug={"error": str(e)})
