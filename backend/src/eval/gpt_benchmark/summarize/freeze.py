"""
Freeze document content + chunk boundaries + summarization prompt.

Read-only: loads already-ingested chunks from storage. Does not re-parse,
re-chunk, or call production summarization pipelines / HTTP.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from src.eval.gpt_benchmark.freeze import hash_context, hash_prompt
from src.eval.gpt_benchmark.summarize.prompts import (
    SUMMARIZATION_TASK_LABEL,
    build_summarization_messages,
    prompt_metadata,
)
from src.eval.gpt_benchmark.summarize.suites import SummarizationSuite, suite_profile
from src.eval.gpt_benchmark.versions import (
    DOCUMENT_FREEZE_VERSION,
    SUMMARIZE_PROMPT_VERSION,
)


@dataclass
class FrozenSummarizationInput:
    """Immutable-by-convention inputs shared by every summarization participant."""

    document_id: str
    task_label: str
    document_text: str
    context_hash: str
    system_prompt: str
    user_prompt: str
    prompt_hash: str
    messages: List[Dict[str, str]]
    chunk_boundaries: List[Dict[str, Any]] = field(default_factory=list)
    chunk_count: int = 0
    total_chunks_available: int = 0
    document_chars: int = 0
    context_tokens: int = 0
    suite: str = "summarization-smoke"
    prompt_version: str = SUMMARIZE_PROMPT_VERSION
    document_freeze_version: str = DOCUMENT_FREEZE_VERSION
    filename: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def frozen_prompt_record(self) -> Dict[str, Any]:
        return {
            "system_prompt": self.system_prompt,
            "user_prompt": self.user_prompt,
            "document_text": self.document_text,
            "prompt_hash": self.prompt_hash,
            "context_hash": self.context_hash,
            "prompt_version": self.prompt_version,
            "document_freeze_version": self.document_freeze_version,
            "chunk_count": self.chunk_count,
            "chunk_boundaries": list(self.chunk_boundaries),
            "document_id": self.document_id,
            "messages": self.messages,
            "task_label": self.task_label,
        }


def _sort_chunk_rows(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def _key(r: Dict[str, Any]) -> tuple:
        idx = r.get("index")
        try:
            return (0, int(idx))
        except (TypeError, ValueError):
            return (1, str(idx or ""))

    return sorted(list(rows), key=_key)


def _apply_suite_window(
    rows: Sequence[Dict[str, Any]],
    profile: SummarizationSuite,
) -> tuple[List[Dict[str, Any]], str]:
    selected = list(rows)
    if profile.max_chunks is not None:
        selected = selected[: max(0, int(profile.max_chunks))]

    parts: List[str] = []
    boundaries: List[Dict[str, Any]] = []
    char_budget = profile.max_chars
    for r in selected:
        text = (r.get("text") or "").strip()
        if not text:
            continue
        prefix = "\n\n".join(parts)
        sep = "\n\n" if parts else ""
        tentative = prefix + sep + text
        if char_budget is not None and len(tentative) > char_budget:
            remain = char_budget - (len(prefix) + len(sep))
            if remain <= 0:
                break
            text = text[:remain]
            if not text:
                break
        start = len(prefix) + len(sep)
        parts.append(text)
        end = start + len(text)
        boundaries.append(
            {
                "index": r.get("index"),
                "char_start": start,
                "char_end": end,
                "chars": len(text),
            }
        )
        if char_budget is not None and end >= char_budget:
            break
    document_text = "\n\n".join(parts)
    return boundaries, document_text


def freeze_document_for_summarization(
    *,
    document_id: str,
    suite: str = "summarization-smoke",
    filename: Optional[str] = None,
) -> FrozenSummarizationInput:
    """
    Load ingested chunks once, apply suite window, freeze prompt for all models.
    """
    from src.memory import storage

    profile = suite_profile(suite)
    raw = storage.retrieve_chunks(document_id) or []
    if not raw:
        raise FileNotFoundError(
            f"No stored chunks for document_id={document_id!r}. "
            "Ingest via the normal upload/summarize flow first."
        )
    ordered = _sort_chunk_rows(raw)
    boundaries, document_text = _apply_suite_window(ordered, profile)
    if not document_text.strip():
        raise ValueError(f"Frozen document text is empty for {document_id!r}")

    messages = build_summarization_messages(document_text)
    system_prompt = messages[0]["content"] if messages else ""
    user_prompt = messages[1]["content"] if len(messages) > 1 else ""

    # Rough token estimate for energy helpers (same heuristic as RAG freeze)
    context_tokens = max(1, len(document_text) // 4)

    return FrozenSummarizationInput(
        document_id=document_id,
        task_label=SUMMARIZATION_TASK_LABEL,
        document_text=document_text,
        context_hash=hash_context(document_text),
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        prompt_hash=hash_prompt(
            system_prompt,
            user_prompt,
            prompt_version=SUMMARIZE_PROMPT_VERSION,
        ),
        messages=messages,
        chunk_boundaries=boundaries,
        chunk_count=len(boundaries),
        total_chunks_available=len(ordered),
        document_chars=len(document_text),
        context_tokens=context_tokens,
        suite=profile.suite_id,
        prompt_version=SUMMARIZE_PROMPT_VERSION,
        document_freeze_version=DOCUMENT_FREEZE_VERSION,
        filename=filename,
    )


def frozen_summarization_fingerprint(frozen: FrozenSummarizationInput) -> str:
    payload = {
        "messages": frozen.messages,
        "context_hash": frozen.context_hash,
        "prompt_hash": frozen.prompt_hash,
        "prompt": prompt_metadata(),
        "document_freeze_version": frozen.document_freeze_version,
        "document_id": frozen.document_id,
        "chunk_count": frozen.chunk_count,
        "suite": frozen.suite,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
