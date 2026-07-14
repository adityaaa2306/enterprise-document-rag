"""
Document Structure Pipeline.

layout blocks → heading validation → semantic sections → merge → pack
→ AdaptiveChunk list compatible with existing map/RAG/carbon path.
"""
from __future__ import annotations

import logging
import statistics
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from src.chunking.types import AdaptiveChunk, ParentNode
from src.core.config import settings
from src.structure.heading_validator import validate_headings
from src.structure.packing import pack_sections
from src.structure.section_builder import build_semantic_sections, sections_to_tree
from src.structure.semantic_merge import merge_sections
from src.structure.types import LayoutBlock, StructureDiagnostics

log = logging.getLogger(__name__)

EmbedFn = Callable[[List[str]], List[List[float]]]


def _elem_content(el: Any) -> str:
    if isinstance(el, LayoutBlock):
        return (el.text or "").strip()
    if hasattr(el, "content"):
        return (el.content or "").strip()
    if hasattr(el, "text") and not hasattr(el, "type"):
        # LayoutBlock-like
        return str(getattr(el, "text") or "").strip()
    if isinstance(el, dict):
        return str(el.get("content") or el.get("text") or "").strip()
    return str(el or "").strip()


def _elem_type(el: Any) -> str:
    if isinstance(el, LayoutBlock):
        return el.block_type or "Text"
    if hasattr(el, "type"):
        return str(el.type)
    if isinstance(el, dict):
        return str(el.get("type") or el.get("block_type") or "Text")
    return "Text"


def elements_to_layout_blocks(elements: Sequence[Any]) -> List[LayoutBlock]:
    """
    Expand triage elements into line-aware layout blocks.

    Title labels from triage are preserved only as weak priors — validation decides.
    Multi-line Text is split into lines so false page-level blobs can be scored.
    """
    blocks: List[LayoutBlock] = []
    page = 0
    for el in elements:
        text = _elem_content(el)
        if not text:
            continue
        t = _elem_type(el)
        # Tables stay atomic
        if t == "Table" or text.startswith("--- TABLE"):
            blocks.append(
                LayoutBlock(
                    index=len(blocks),
                    text=text,
                    block_type="Table",
                    page=page,
                    meta={"atomic": True},
                )
            )
            continue
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        # Heuristic: a large block without newlines is one paragraph
        if len(lines) <= 1:
            blocks.append(
                LayoutBlock(
                    index=len(blocks),
                    text=text,
                    block_type=t,
                    page=page,
                )
            )
        else:
            # Page-like: advance page counter when we see many lines from one element
            if len(lines) >= 8:
                page += 1
            for ln in lines:
                # Short lines keep triage Title prior if parent was Title
                bt = "Title" if (t == "Title" or len(ln.split()) <= 12) else t
                if t != "Title":
                    bt = "Text"
                blocks.append(
                    LayoutBlock(
                        index=len(blocks),
                        text=ln,
                        block_type=bt if t == "Title" else "Text",
                        page=page or 1,
                    )
                )
    # Reindex
    for i, b in enumerate(blocks):
        b.index = i
    return blocks


class DocumentStructurePipeline:
    """Production structure parser used before map summarization."""

    def __init__(self, embed_fn: Optional[EmbedFn] = None):
        self.embed_fn = embed_fn

    def run(
        self,
        elements: Sequence[Any],
        *,
        document_id: str,
    ) -> Tuple[List[AdaptiveChunk], List[ParentNode], Dict[str, Any]]:
        blocks = elements_to_layout_blocks(elements)
        diag = StructureDiagnostics(raw_layout_blocks=len(blocks))

        decisions, accepted, rejected = validate_headings(blocks)
        diag.heading_candidates = len(decisions)
        diag.validated_headings = len(accepted)
        diag.rejected_headings = len(rejected)
        diag.validated = [
            {
                "text": d.text,
                "confidence": d.confidence,
                "class": d.classification,
                "level": d.level,
            }
            for d in accepted
        ]
        diag.rejected = [
            {
                "text": d.text,
                "confidence": d.confidence,
                "class": d.classification,
                "reasons": d.reject_reasons,
            }
            for d in rejected[:200]
        ]

        sections = build_semantic_sections(blocks, accepted, document_id=document_id)
        diag.semantic_sections = len(sections)

        merged, merge_events = merge_sections(sections, embed_fn=self.embed_fn)
        diag.merged_sections = len(merged)
        diag.merge_events = merge_events
        diag.section_tree = sections_to_tree(merged)

        chunks, parents, split_events = pack_sections(merged, document_id=document_id)
        diag.split_events = split_events
        diag.packed_chunks = len(chunks)
        toks = [c.token_estimate or max(1, len(c.content) // 4) for c in chunks]
        if toks:
            diag.average_chunk_tokens = round(statistics.mean(toks), 1)
            diag.median_chunk_tokens = round(statistics.median(toks), 1)
            diag.min_chunk_tokens = min(toks)
            diag.max_chunk_tokens = max(toks)

        meta = {
            "adaptive": True,
            "structure_parser": True,
            "section_count": len(parents),
            "chunk_count": len(chunks),
            "raw_chunk_count": len(blocks),
            "raw_layout_blocks": len(blocks),
            "validated_headings": len(accepted),
            "rejected_headings": len(rejected),
            "semantic_sections": len(sections),
            "merged_sections": len(merged),
            "table_chunks": sum(1 for c in chunks if c.chunk_kind == "table"),
            "structure_diagnostics": diag.model_dump(),
            "document_structure_tree": diag.section_tree,
            "max_tokens": int(getattr(settings, "STRUCTURE_MAX_TOKENS", 1200) or 1200),
            "min_tokens_before_sim_split": int(
                getattr(settings, "STRUCTURE_MIN_TOKENS", 450) or 450
            ),
            "sim_threshold": float(
                getattr(settings, "STRUCTURE_MERGE_SIM_MIN", 0.28) or 0.28
            ),
            "max_chunk_count": int(getattr(settings, "CHUNK_MAX_COUNT", 512) or 512),
        }
        log.info(
            "StructurePipeline: blocks=%s validated_headings=%s sections=%s→%s packed=%s "
            "(avg_tok=%s median=%s)",
            len(blocks),
            len(accepted),
            len(sections),
            len(merged),
            len(chunks),
            diag.average_chunk_tokens,
            diag.median_chunk_tokens,
        )
        return chunks, parents, meta


def build_structured_chunks(
    elements: Sequence[Any],
    document_id: str,
    embed_fn: Optional[EmbedFn] = None,
) -> Tuple[List[AdaptiveChunk], List[ParentNode], Dict[str, Any]]:
    return DocumentStructurePipeline(embed_fn=embed_fn).run(
        elements, document_id=document_id
    )
