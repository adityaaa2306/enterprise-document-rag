"""
ChunkingService — adaptive, hierarchy-aware chunking (Phase 2.A).

Not an agent: deterministic rules over triage elements.
- Title elements open a new section parent
- Tables stay atomic
- Text/List merge within a section until max tokens (similarity only after a min fill)
- Final consolidate pass packs tiny fragments and enforces CHUNK_MAX_COUNT
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from src.chunking.types import AdaptiveChunk, ParentNode, ChunkKind, ChunkType
from src.core.config import settings
from src.monitoring.chunking_forensics import ChunkForensicRecord

log = logging.getLogger(__name__)

EmbedFn = Callable[[List[str]], List[List[float]]]


def estimate_tokens(text: str) -> int:
    try:
        from src.perf.cache import get_token_count

        return get_token_count(text)
    except Exception:
        return max(1, len(text or "") // 4)


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na <= 1e-9 or nb <= 1e-9:
        return 0.0
    return dot / (na * nb)


def _lexical_overlap(a: str, b: str) -> float:
    """Fallback similarity when embeddings are unavailable."""
    ta = set(re.findall(r"[a-zA-Z]{3,}", (a or "").lower()))
    tb = set(re.findall(r"[a-zA-Z]{3,}", (b or "").lower()))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(1, len(ta | tb))


def _elem_type(el: Any) -> ChunkType:
    if hasattr(el, "type"):
        t = str(el.type)
        if t in ("Title", "Text", "Table", "List", "Other"):
            return t  # type: ignore
    if isinstance(el, dict):
        t = str(el.get("type", "Text"))
        if t in ("Title", "Text", "Table", "List", "Other"):
            return t  # type: ignore
    return "Text"


def _elem_content(el: Any) -> str:
    if hasattr(el, "content"):
        return el.content or ""
    if isinstance(el, dict):
        return el.get("content") or el.get("text") or ""
    return str(el)


def _kind_for(t: ChunkType) -> ChunkKind:
    return {
        "Title": "title",
        "Table": "table",
        "List": "list",
        "Text": "text",
        "Other": "text",
    }.get(t, "text")  # type: ignore


class ChunkingService:
    """
    Build AdaptiveChunk list + ParentNode tree from triage chunks/elements.
    """

    def __init__(
        self,
        max_tokens: Optional[int] = None,
        sim_threshold: Optional[float] = None,
        embed_fn: Optional[EmbedFn] = None,
        min_tokens_before_sim_split: Optional[int] = None,
        max_chunk_count: Optional[int] = None,
        title_as_chunk: Optional[bool] = None,
        forensics: Any = None,
    ):
        self.max_tokens = max_tokens if max_tokens is not None else settings.CHUNK_MAX_TOKENS
        self.sim_threshold = (
            sim_threshold if sim_threshold is not None else settings.CHUNK_SIM_THRESHOLD
        )
        self.min_tokens_before_sim_split = (
            min_tokens_before_sim_split
            if min_tokens_before_sim_split is not None
            else int(getattr(settings, "CHUNK_MIN_TOKENS_BEFORE_SIM_SPLIT", 500) or 500)
        )
        self.max_chunk_count = (
            max_chunk_count
            if max_chunk_count is not None
            else int(getattr(settings, "CHUNK_MAX_COUNT", 512) or 512)
        )
        self.title_as_chunk = (
            title_as_chunk
            if title_as_chunk is not None
            else bool(getattr(settings, "CHUNK_TITLE_AS_CHUNK", False))
        )
        self.overlap_tokens = int(getattr(settings, "CHUNK_OVERLAP_TOKENS", 40) or 0)
        self.min_tokens = int(getattr(settings, "CHUNK_MIN_TOKENS", 120) or 120)
        self.force_cap = bool(getattr(settings, "CHUNK_FORCE_CAP", False))
        self.embed_fn = embed_fn
        # Observation only — never affects control flow when None/disabled.
        self.forensics = forensics

    def build(
        self,
        elements: List[Any],
        document_id: str,
    ) -> Tuple[List[AdaptiveChunk], List[ParentNode], Dict[str, Any]]:
        if not elements:
            return [], [], {"adaptive": True, "section_count": 0}

        fx = self.forensics
        parents: List[ParentNode] = []
        chunks: List[AdaptiveChunk] = []
        # Per-chunk forensic provenance recorded at emission time (observation only).
        emit_meta: List[Dict[str, Any]] = []

        current_parent: Optional[ParentNode] = None
        buffer: List[Tuple[ChunkType, str]] = []  # pending text/list pieces

        def flush_buffer(*, reason: str = "forced_flush", detail: str = ""):
            nonlocal buffer
            if not buffer:
                return
            merged_type: ChunkType = "Text"
            kinds = {t for t, _ in buffer}
            if kinds == {"List"}:
                merged_type = "List"
            piece_types = [t for t, _ in buffer]
            text = "\n\n".join(c for _, c in buffer if c.strip())
            n_pieces = len(buffer)
            buf_tokens = estimate_tokens(text)
            buffer = []
            if not text.strip():
                return
            if fx is not None and getattr(fx, "enabled", False):
                fx.record_split(
                    reason,
                    detail=detail or f"flush {n_pieces} buffer piece(s)",
                    buffer_tokens_before=buf_tokens,
                    section_title=current_parent.title if current_parent else None,
                    element_type=merged_type,
                )
                if n_pieces > 1:
                    fx.record_merge(
                        "same_section_buffer_pack",
                        detail=f"merged {n_pieces} triage pieces under section",
                        chunks_merged=n_pieces,
                        tokens_after=buf_tokens,
                        section_title=current_parent.title if current_parent else None,
                    )
            self._append_chunk(
                chunks,
                parents,
                current_parent,
                document_id,
                merged_type,
                text,
                kind="merged" if len(text) > 0 else "text",
            )
            emit_meta.append(
                {
                    "reason_split": reason,
                    "reason_merge": (
                        "same_section_buffer_pack" if n_pieces > 1 else "single_piece"
                    ),
                    "element_types": piece_types,
                    "paragraphs": sum(
                        1 for t in piece_types if t in ("Text", "Other", "Title")
                    ),
                    "tables": sum(1 for t in piece_types if t == "Table"),
                }
            )

        def ensure_default_parent():
            nonlocal current_parent
            if current_parent is None:
                current_parent = ParentNode(
                    id=f"{document_id}_section_0",
                    document_id=document_id,
                    title="Document",
                    section_path="Document",
                    child_chunk_indices=[],
                )
                parents.append(current_parent)

        for el in elements:
            t = _elem_type(el)
            content = _elem_content(el).strip()
            if not content:
                continue

            if t == "Title":
                flush_buffer(reason="new_heading", detail=f"heading={content[:80]}")
                section_idx = len(parents)
                current_parent = ParentNode(
                    id=f"{document_id}_section_{section_idx}",
                    document_id=document_id,
                    title=content[:200],
                    section_path=content[:200],
                    child_chunk_indices=[],
                )
                parents.append(current_parent)
                if self.title_as_chunk:
                    self._append_chunk(
                        chunks,
                        parents,
                        current_parent,
                        document_id,
                        "Title",
                        content,
                        kind="title",
                    )
                    emit_meta.append(
                        {
                            "reason_split": "new_heading",
                            "reason_merge": "title_as_chunk",
                            "element_types": ["Title"],
                            "paragraphs": 0,
                            "tables": 0,
                        }
                    )
                else:
                    # Fold heading into the next body buffer so it isn't a solo map call
                    buffer.append(("Text", content))
                continue

            if t == "Table":
                flush_buffer(reason="table_boundary", detail="flush before atomic table")
                ensure_default_parent()
                if fx is not None and getattr(fx, "enabled", False):
                    fx.record_split(
                        "table_boundary",
                        detail="atomic table chunk",
                        incoming_tokens=estimate_tokens(content),
                        section_title=current_parent.title if current_parent else None,
                        element_type="Table",
                    )
                self._append_chunk(
                    chunks,
                    parents,
                    current_parent,
                    document_id,
                    "Table",
                    content,
                    kind="table",
                )
                emit_meta.append(
                    {
                        "reason_split": "table_boundary",
                        "reason_merge": "atomic_table",
                        "element_types": ["Table"],
                        "paragraphs": 0,
                        "tables": 1,
                    }
                )
                continue

            # Text / List / Other — pack to token budget; similarity only after min fill
            ensure_default_parent()
            if not buffer:
                buffer.append((t, content))
                continue

            prev_text = buffer[-1][1]
            should_split = False
            split_reason = ""
            sim_val: Optional[float] = None

            tentative = "\n\n".join([c for _, c in buffer] + [content])
            tentative_tokens = estimate_tokens(tentative)
            if tentative_tokens > self.max_tokens:
                should_split = True
                split_reason = "max_token_threshold"
            else:
                buf_tokens = estimate_tokens("\n\n".join(c for _, c in buffer))
                if buf_tokens >= self.min_tokens_before_sim_split:
                    sim_val = self._similarity(prev_text, content)
                    if sim_val < self.sim_threshold:
                        should_split = True
                        split_reason = "semantic_similarity_drop"

            if should_split:
                # Capture overlap from the buffer before flush (max-size splits).
                overlap_prefix = ""
                if self.overlap_tokens > 0 and buffer:
                    joined = "\n\n".join(c for _, c in buffer)
                    # Approx chars for overlap tokens
                    take = max(0, int(self.overlap_tokens) * 4)
                    if take > 0 and len(joined) > take:
                        overlap_prefix = joined[-take:]
                detail = split_reason
                if split_reason == "semantic_similarity_drop" and sim_val is not None:
                    detail = f"sim={sim_val:.3f} < threshold={self.sim_threshold}"
                elif split_reason == "max_token_threshold":
                    detail = f"tentative_tokens={tentative_tokens} > max={self.max_tokens}"
                flush_buffer(reason=split_reason or "forced_flush", detail=detail)
                if overlap_prefix:
                    buffer.append(("Text", overlap_prefix))
            else:
                if fx is not None and getattr(fx, "enabled", False):
                    fx.record_merge(
                        "same_section_continue",
                        detail="appending triage piece into buffer",
                        tokens_before=estimate_tokens(
                            "\n\n".join(c for _, c in buffer)
                        ),
                        section_title=current_parent.title if current_parent else None,
                        similarity=sim_val,
                    )
            buffer.append((t, content))

        flush_buffer(reason="end_of_document", detail="final buffer flush")

        raw_count = len(chunks)
        if fx is not None and getattr(fx, "enabled", False):
            fx.semantic_group_count = raw_count
            fx.section_count = len(parents)

        if self._needs_consolidate(chunks):
            chunks = self._consolidate(chunks, parents, document_id)
            # Consolidation rebuilds chunk list; emit_meta no longer 1:1 — rebuild below.
            emit_meta = []
        self._reindex(chunks, parents)

        if fx is not None and getattr(fx, "enabled", False):
            fx.packed_chunk_count = len(chunks)
            fx.chunk_records = []
            for i, ch in enumerate(chunks):
                meta_i = emit_meta[i] if i < len(emit_meta) else {}
                paras = max(1, (ch.content or "").count("\n\n") + 1) if ch.content else 0
                is_table = ch.chunk_kind == "table" or ch.type == "Table"
                fx.chunk_records.append(
                    ChunkForensicRecord(
                        chunk_index=i,
                        section=ch.section_path,
                        heading=ch.section_path,
                        element_types=list(meta_i.get("element_types") or [ch.type]),
                        paragraphs=int(meta_i.get("paragraphs") or paras),
                        tables=int(meta_i.get("tables") or (1 if is_table else 0)),
                        images=0,
                        estimated_tokens=estimate_tokens(ch.content or ""),
                        char_count=len(ch.content or ""),
                        reason_split=meta_i.get("reason_split")
                        or ("table_boundary" if is_table else "section_or_consolidate_pack"),
                        reason_merge=meta_i.get("reason_merge")
                        or ("atomic_table" if is_table else "packed"),
                        content_preview=(ch.content or "")[:240],
                    )
                )

        meta = {
            "adaptive": True,
            "section_count": len(parents),
            "chunk_count": len(chunks),
            "raw_chunk_count": raw_count,
            "max_tokens": self.max_tokens,
            "sim_threshold": self.sim_threshold,
            "min_tokens_before_sim_split": self.min_tokens_before_sim_split,
            "max_chunk_count": self.max_chunk_count,
            "table_chunks": sum(1 for c in chunks if c.chunk_kind == "table"),
        }
        log.info(
            f"ChunkingService: {len(chunks)} chunks (raw={raw_count}), "
            f"{len(parents)} sections (tables={meta['table_chunks']}, "
            f"cap={self.max_chunk_count})"
        )
        return chunks, parents, meta

    def _needs_consolidate(self, chunks: List[AdaptiveChunk]) -> bool:
        """Pack only when over the hard cap or the average fragment is tiny."""
        if not chunks:
            return False
        if len(chunks) > max(1, int(self.max_chunk_count)):
            return True
        avg = sum(estimate_tokens(c.content) for c in chunks) / len(chunks)
        tiny_threshold = max(80, int(self.min_tokens_before_sim_split) // 4)
        return avg < tiny_threshold and len(chunks) > 8

    def _consolidate(
        self,
        chunks: List[AdaptiveChunk],
        parents: List[ParentNode],
        document_id: str,
    ) -> List[AdaptiveChunk]:
        """
        Pack consecutive non-table chunks up to max_tokens, then raise the pack
        size until we are under CHUNK_MAX_COUNT. Tables stay atomic.
        """
        if not chunks:
            return chunks

        pack_limit = max(64, int(self.max_tokens))
        hard_cap = max(1, int(self.max_chunk_count))
        fx = self.forensics

        for round_i in range(8):
            before = len(chunks)
            packed = self._pack_once(chunks, document_id, pack_limit)
            after = len(packed)
            if fx is not None and getattr(fx, "enabled", False):
                fx.consolidate_rounds.append(
                    {
                        "round": round_i,
                        "pack_limit": pack_limit,
                        "before": before,
                        "after": after,
                        "hard_cap": hard_cap,
                    }
                )
                if after < before:
                    fx.record_merge(
                        "consolidate_pack",
                        detail=f"round={round_i} pack_limit={pack_limit}",
                        chunks_merged=before - after,
                        tokens_before=before,
                        tokens_after=after,
                    )
            if len(packed) <= hard_cap:
                return packed
            # Still too many — allow larger packs
            pack_limit = max(pack_limit + 1, int(pack_limit * 1.75))
            chunks = packed
            log.warning(
                "ChunkingService: %s chunks exceed soft cap %s — repacking with max_tokens=%s",
                len(chunks),
                hard_cap,
                pack_limit,
            )

        if self.force_cap:
            if fx is not None and getattr(fx, "enabled", False):
                fx.record_split(
                    "force_cap",
                    detail=f"forcing down to {hard_cap} from {len(chunks)}",
                )
            return self._force_cap(chunks, document_id, hard_cap)
        # Soft mode for large docs: keep structure; hierarchy handles fan-in.
        log.warning(
            "ChunkingService: leaving %s chunks (cap=%s, force_cap=False) for hierarchical compile",
            len(chunks),
            hard_cap,
        )
        if fx is not None and getattr(fx, "enabled", False):
            fx.record_split(
                "soft_cap_leave",
                detail=(
                    f"leaving {len(chunks)} chunks above cap={hard_cap} "
                    f"(force_cap=False; parent-boundary packing)"
                ),
            )
        return chunks

    def _pack_once(
        self,
        chunks: List[AdaptiveChunk],
        document_id: str,
        pack_limit: int,
    ) -> List[AdaptiveChunk]:
        out: List[AdaptiveChunk] = []
        buf: List[AdaptiveChunk] = []

        def flush():
            nonlocal buf
            if not buf:
                return
            if len(buf) == 1:
                out.append(buf[0])
            else:
                text = "\n\n".join(c.content for c in buf if (c.content or "").strip())
                parent_id = buf[0].parent_id
                section_path = buf[0].section_path
                out.append(
                    AdaptiveChunk(
                        id=f"{document_id}_{len(out)}",
                        document_id=document_id,
                        chunk_index=len(out),
                        type="Text",
                        content=text,
                        parent_id=parent_id,
                        section_path=section_path,
                        chunk_kind="merged",
                        token_estimate=estimate_tokens(text),
                    )
                )
            buf = []

        for ch in chunks:
            is_table = ch.chunk_kind == "table" or ch.type == "Table"
            if is_table:
                flush()
                out.append(ch)
                continue
            # Keep section boundaries intact when packing
            if buf and ch.parent_id != buf[0].parent_id:
                flush()
            tentative = "\n\n".join(
                [c.content for c in buf] + [ch.content]
            ) if buf else ch.content
            if buf and estimate_tokens(tentative) > pack_limit:
                flush()
            buf.append(ch)
        flush()
        return out

    def _force_cap(
        self,
        chunks: List[AdaptiveChunk],
        document_id: str,
        hard_cap: int,
    ) -> List[AdaptiveChunk]:
        if len(chunks) <= hard_cap:
            return chunks
        # Evenly merge into hard_cap groups
        n = len(chunks)
        out: List[AdaptiveChunk] = []
        for i in range(hard_cap):
            start = (i * n) // hard_cap
            end = ((i + 1) * n) // hard_cap
            group = chunks[start:end]
            if not group:
                continue
            if len(group) == 1:
                out.append(group[0])
                continue
            text = "\n\n".join(c.content for c in group if (c.content or "").strip())
            out.append(
                AdaptiveChunk(
                    id=f"{document_id}_{len(out)}",
                    document_id=document_id,
                    chunk_index=len(out),
                    type="Text",
                    content=text,
                    parent_id=group[0].parent_id,
                    section_path=group[0].section_path,
                    chunk_kind="merged",
                    token_estimate=estimate_tokens(text),
                )
            )
        return out

    def _reindex(self, chunks: List[AdaptiveChunk], parents: List[ParentNode]) -> None:
        for i, ch in enumerate(chunks):
            ch.chunk_index = i
            ch.id = f"{ch.document_id}_{i}"
            ch.estimate_tokens()

        parent_by_id = {p.id: p for p in parents}
        for p in parents:
            p.child_chunk_indices = []
        for ch in chunks:
            if ch.parent_id and ch.parent_id in parent_by_id:
                parent_by_id[ch.parent_id].child_chunk_indices.append(ch.chunk_index)

    def _similarity(self, a: str, b: str) -> float:
        if self.embed_fn is not None:
            try:
                vecs = self.embed_fn([a[:2000], b[:2000]])
                if len(vecs) >= 2:
                    return _cosine(vecs[0], vecs[1])
            except Exception as e:
                log.warning(f"Chunking embed similarity failed, using lexical: {e}")
        return _lexical_overlap(a, b)

    def _append_chunk(
        self,
        chunks: List[AdaptiveChunk],
        parents: List[ParentNode],
        parent: Optional[ParentNode],
        document_id: str,
        ctype: ChunkType,
        content: str,
        kind: ChunkKind,
    ) -> None:
        idx = len(chunks)
        parent_id = parent.id if parent else None
        section_path = parent.section_path if parent else None
        ch = AdaptiveChunk(
            id=f"{document_id}_{idx}",
            document_id=document_id,
            chunk_index=idx,
            type=ctype,
            content=content,
            parent_id=parent_id,
            section_path=section_path,
            chunk_kind=kind if kind != "merged" else _kind_for(ctype),
            token_estimate=estimate_tokens(content),
        )
        if kind == "merged":
            ch.chunk_kind = "merged"
        chunks.append(ch)


def build_adaptive_chunks(
    elements: List[Any],
    document_id: str,
    embed_fn: Optional[EmbedFn] = None,
) -> Tuple[List[AdaptiveChunk], List[ParentNode], Dict[str, Any]]:
    """Module-level convenience wrapper."""
    return ChunkingService(embed_fn=embed_fn).build(elements, document_id)
