"""
Retrieve once per question and freeze context + prompt for all models.

Reuses production RetrievalService + ContextAssembler for context acquisition
only. Generation uses a separate OpenAI client — not NIM / ResponseAgent.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from src.eval.gpt_benchmark.prompts import build_frozen_messages, prompt_metadata
from src.eval.gpt_benchmark.versions import PROMPT_VERSION, RETRIEVAL_VERSION


@dataclass
class FrozenBenchmarkInput:
    """Immutable-by-convention inputs shared by every model for one question."""

    question: str
    document_id: str
    context_text: str
    context_hash: str
    system_prompt: str
    user_prompt: str
    prompt_hash: str
    messages: List[Dict[str, str]]
    passage_chunk_ids: List[str] = field(default_factory=list)
    chunk_count: int = 0
    context_tokens: int = 0
    retrieval_debug: Dict[str, Any] = field(default_factory=dict)
    pack_stats: Dict[str, Any] = field(default_factory=dict)
    retrieval_version: str = RETRIEVAL_VERSION
    prompt_version: str = PROMPT_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def frozen_prompt_record(self) -> Dict[str, Any]:
        """Explicit reproducibility payload required for scientific comparison."""
        return {
            "system_prompt": self.system_prompt,
            "user_prompt": self.user_prompt,
            "retrieved_context": self.context_text,
            "prompt_hash": self.prompt_hash,
            "context_hash": self.context_hash,
            "prompt_version": self.prompt_version,
            "retrieval_version": self.retrieval_version,
            "chunk_count": self.chunk_count,
            "passage_chunk_ids": list(self.passage_chunk_ids),
            "document_id": self.document_id,
            "messages": self.messages,
        }


def hash_context(context_text: str) -> str:
    return hashlib.sha256((context_text or "").encode("utf-8")).hexdigest()


def hash_prompt(
    system_prompt: str,
    user_prompt: str,
    *,
    prompt_version: Optional[str] = None,
) -> str:
    """Deterministic hash over the complete frozen prompt (system + user)."""
    payload = {
        "prompt_version": prompt_version or PROMPT_VERSION,
        "system_prompt": system_prompt or "",
        "user_prompt": user_prompt or "",
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def freeze_retrieval(
    *,
    document_id: str,
    question: str,
    assemble_tier: str = "heavy",
) -> FrozenBenchmarkInput:
    """
    Run retrieval + context assembly **once** and freeze the resulting prompt.

    Does not call any chat/completion model. Callers must reuse this object
    for every benchmark model on this question.
    """
    from src.context.assembler import ContextAssembler
    from src.retrieval.service import RetrievalService

    retrieval = RetrievalService().search(query=question, document_id=document_id)
    pack = ContextAssembler().pack(
        retrieval.passages,
        tier=assemble_tier,
        query=question,
    )
    context_text = pack.context_text or ""
    messages = build_frozen_messages(question, context_text)
    system_prompt = messages[0]["content"] if messages else ""
    user_prompt = messages[1]["content"] if len(messages) > 1 else ""

    chunk_ids: List[str] = []
    for p in pack.passages or []:
        cids = getattr(p, "chunk_ids", None) or []
        chunk_ids.extend(list(cids))
    # Stable order for reproducibility of chunk_count / ids
    # Keep retrieval packing order (do not sort) — order is part of the freeze.

    return FrozenBenchmarkInput(
        question=question,
        document_id=document_id,
        context_text=context_text,
        context_hash=hash_context(context_text),
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        prompt_hash=hash_prompt(system_prompt, user_prompt),
        messages=messages,
        passage_chunk_ids=chunk_ids,
        chunk_count=len(chunk_ids),
        context_tokens=int(getattr(pack, "tokens_used", 0) or 0),
        retrieval_debug=dict(retrieval.debug or {}),
        pack_stats=dict(pack.stats or {}),
        retrieval_version=RETRIEVAL_VERSION,
        prompt_version=PROMPT_VERSION,
    )


def frozen_input_fingerprint(frozen: FrozenBenchmarkInput) -> str:
    """Stable hash over the exact model inputs (messages + versions)."""
    payload = {
        "messages": frozen.messages,
        "context_hash": frozen.context_hash,
        "prompt_hash": frozen.prompt_hash,
        "prompt": prompt_metadata(),
        "retrieval_version": frozen.retrieval_version,
        "document_id": frozen.document_id,
        "chunk_count": frozen.chunk_count,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def resolve_document_id(
    *,
    document_id: Optional[str] = None,
    filename: Optional[str] = None,
) -> str:
    """
    Resolve a document_id for benchmarking.

    Prefer an explicit document_id. Otherwise look up the newest job whose
    filename matches (case-insensitive basename).
    """
    if document_id:
        return str(document_id).strip()

    if not filename:
        raise ValueError("Provide --document-id or --filename")

    from src.db.session import get_session
    from src.db.models import JobModel

    target = filename.replace("\\", "/").split("/")[-1].strip().lower()
    db = get_session()
    try:
        rows = (
            db.query(JobModel)
            .filter(JobModel.filename.isnot(None))
            .order_by(JobModel.created_at.desc())
            .limit(200)
            .all()
        )
        for row in rows:
            name = (row.filename or "").replace("\\", "/").split("/")[-1].strip().lower()
            if name == target:
                return str(row.id)
    finally:
        db.close()

    raise FileNotFoundError(
        f"No ingested document found for filename={filename!r}. "
        "Ingest the PDF via the normal upload/summarize flow first, then pass "
        "--document-id <uuid>."
    )
