"""Adaptive packing of semantic sections into map-summarize chunks."""
from __future__ import annotations

import logging
from typing import List, Optional, Sequence, Tuple

from src.chunking.service import estimate_tokens
from src.chunking.types import AdaptiveChunk, ParentNode
from src.core.config import settings
from src.structure.types import SemanticSection

log = logging.getLogger(__name__)


def _split_oversized(
    sec: SemanticSection,
    max_tokens: int,
) -> List[str]:
    """Split a single oversized section on paragraph boundaries only."""
    text = sec.body_text()
    if estimate_tokens(text) <= max_tokens:
        return [text]
    parts: List[str] = []
    buf: List[str] = []
    pieces = []
    if sec.heading:
        pieces.append(sec.heading)
    pieces.extend(sec.paragraphs or [])
    if not pieces:
        pieces = [text]
    for piece in pieces:
        tentative = "\n\n".join(buf + [piece])
        if buf and estimate_tokens(tentative) > max_tokens:
            parts.append("\n\n".join(buf))
            buf = [piece]
        else:
            buf.append(piece)
    # Attach tables/captions/equations to last part when possible
    extras = sec.tables + sec.lists + sec.captions + sec.equations + sec.figures
    if buf:
        tail = "\n\n".join(buf + extras)
        if estimate_tokens(tail) <= max_tokens * 1.15:
            parts.append(tail)
        else:
            parts.append("\n\n".join(buf))
            if extras:
                parts.append("\n\n".join(extras))
    elif extras:
        parts.append("\n\n".join(extras))
    return [p for p in parts if p.strip()]


def pack_sections(
    sections: Sequence[SemanticSection],
    *,
    document_id: str,
    target_tokens: Optional[int] = None,
    min_tokens: Optional[int] = None,
    max_tokens: Optional[int] = None,
) -> Tuple[List[AdaptiveChunk], List[ParentNode], List[dict]]:
    """
    Pack semantic sections into AdaptiveChunks.

    Target ~700–900, soft min ~450, hard max ~1200.
    Prefer keeping a whole section intact; never invent a force-cap count.
    """
    target = int(
        target_tokens
        if target_tokens is not None
        else getattr(settings, "STRUCTURE_TARGET_TOKENS", 800) or 800
    )
    min_tok = int(
        min_tokens
        if min_tokens is not None
        else getattr(settings, "STRUCTURE_MIN_TOKENS", 450) or 450
    )
    max_tok = int(
        max_tokens
        if max_tokens is not None
        else getattr(settings, "STRUCTURE_MAX_TOKENS", 1200) or 1200
    )

    parents: List[ParentNode] = []
    chunks: List[AdaptiveChunk] = []
    split_events: List[dict] = []

    buf_secs: List[SemanticSection] = []
    buf_tokens = 0

    def flush(reason: str) -> None:
        nonlocal buf_secs, buf_tokens
        if not buf_secs:
            return
        heading = buf_secs[0].heading or "Section"
        parent = ParentNode(
            id=f"{document_id}_section_{len(parents)}",
            document_id=document_id,
            title=heading[:200],
            section_path=heading[:200],
            child_chunk_indices=[],
        )
        parents.append(parent)
        text = "\n\n".join(s.body_text() for s in buf_secs if s.body_text().strip())
        idx = len(chunks)
        parent.child_chunk_indices.append(idx)
        chunks.append(
            AdaptiveChunk(
                id=f"{document_id}_{idx}",
                document_id=document_id,
                chunk_index=idx,
                type="Text",
                content=text,
                parent_id=parent.id,
                section_path=parent.section_path,
                chunk_kind="merged",
                token_estimate=estimate_tokens(text),
            )
        )
        split_events.append(
            {
                "action": "pack_flush",
                "reason": reason,
                "sections": [s.section_id for s in buf_secs],
                "tokens": estimate_tokens(text),
                "heading": heading,
            }
        )
        buf_secs = []
        buf_tokens = 0

    for sec in sections:
        sec.recount_tokens()
        # Oversized single section → paragraph splits
        if sec.estimated_tokens > max_tok:
            flush("before_oversized_section")
            pieces = _split_oversized(sec, max_tok)
            for pi, piece in enumerate(pieces):
                parent = ParentNode(
                    id=f"{document_id}_section_{len(parents)}",
                    document_id=document_id,
                    title=f"{sec.heading[:160]} ({pi+1})" if sec.heading else f"Part {pi+1}",
                    section_path=sec.heading[:200] if sec.heading else f"Part {pi+1}",
                    child_chunk_indices=[],
                )
                parents.append(parent)
                idx = len(chunks)
                parent.child_chunk_indices.append(idx)
                chunks.append(
                    AdaptiveChunk(
                        id=f"{document_id}_{idx}",
                        document_id=document_id,
                        chunk_index=idx,
                        type="Text",
                        content=piece,
                        parent_id=parent.id,
                        section_path=parent.section_path,
                        chunk_kind="merged",
                        token_estimate=estimate_tokens(piece),
                    )
                )
                split_events.append(
                    {
                        "action": "section_paragraph_split",
                        "reason": f"section_tokens={sec.estimated_tokens}>{max_tok}",
                        "section": sec.section_id,
                        "part": pi,
                        "tokens": estimate_tokens(piece),
                    }
                )
            continue

        # Prefer not crossing major chapter boundaries once the buffer is healthy.
        if (
            buf_secs
            and sec.heading_level <= 1
            and buf_tokens >= max(min_tok // 2, 200)
            and buf_tokens + sec.estimated_tokens > target
        ):
            flush("major_heading_boundary")

        if buf_secs and buf_tokens + sec.estimated_tokens > max_tok:
            flush("max_token_boundary")

        buf_secs.append(sec)
        buf_tokens += sec.estimated_tokens

        # Flush when we reach/exceed target and buffer is healthy
        if buf_tokens >= target and buf_tokens >= min_tok:
            flush("target_pack")

    flush("end_of_document")

    # Second pass: absorb tiny trailing leftovers into previous when safe
    if len(chunks) >= 2:
        last = chunks[-1]
        if last.token_estimate < min_tok:
            prev = chunks[-2]
            combined = prev.content + "\n\n" + last.content
            if estimate_tokens(combined) <= max_tok:
                prev.content = combined
                prev.token_estimate = estimate_tokens(combined)
                split_events.append(
                    {
                        "action": "absorb_tiny_tail",
                        "reason": f"tail_tokens={last.token_estimate}<min={min_tok}",
                        "into": prev.id,
                    }
                )
                # drop last chunk + its parent if exclusive
                dropped_parent = last.parent_id
                chunks.pop()
                parents[:] = [p for p in parents if p.id != dropped_parent]
                for i, ch in enumerate(chunks):
                    ch.chunk_index = i
                    ch.id = f"{document_id}_{i}"
                for p in parents:
                    p.child_chunk_indices = [
                        i for i, ch in enumerate(chunks) if ch.parent_id == p.id
                    ]

    log.info(
        "StructurePack: %s sections → %s chunks (target=%s min=%s max=%s)",
        len(sections),
        len(chunks),
        target,
        min_tok,
        max_tok,
    )
    return chunks, parents, split_events
