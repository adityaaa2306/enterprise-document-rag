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

log = logging.getLogger(__name__)

EmbedFn = Callable[[List[str]], List[List[float]]]


def estimate_tokens(text: str) -> int:
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
            else int(getattr(settings, "CHUNK_MAX_COUNT", 48) or 48)
        )
        self.title_as_chunk = (
            title_as_chunk
            if title_as_chunk is not None
            else bool(getattr(settings, "CHUNK_TITLE_AS_CHUNK", False))
        )
        self.embed_fn = embed_fn

    def build(
        self,
        elements: List[Any],
        document_id: str,
    ) -> Tuple[List[AdaptiveChunk], List[ParentNode], Dict[str, Any]]:
        if not elements:
            return [], [], {"adaptive": True, "section_count": 0}

        parents: List[ParentNode] = []
        chunks: List[AdaptiveChunk] = []

        current_parent: Optional[ParentNode] = None
        buffer: List[Tuple[ChunkType, str]] = []  # pending text/list pieces

        def flush_buffer():
            nonlocal buffer
            if not buffer:
                return
            merged_type: ChunkType = "Text"
            kinds = {t for t, _ in buffer}
            if kinds == {"List"}:
                merged_type = "List"
            text = "\n\n".join(c for _, c in buffer if c.strip())
            buffer = []
            if not text.strip():
                return
            self._append_chunk(
                chunks,
                parents,
                current_parent,
                document_id,
                merged_type,
                text,
                kind="merged" if len(text) > 0 else "text",
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
                flush_buffer()
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
                else:
                    # Fold heading into the next body buffer so it isn't a solo map call
                    buffer.append(("Text", content))
                continue

            if t == "Table":
                flush_buffer()
                ensure_default_parent()
                self._append_chunk(
                    chunks,
                    parents,
                    current_parent,
                    document_id,
                    "Table",
                    content,
                    kind="table",
                )
                continue

            # Text / List / Other — pack to token budget; similarity only after min fill
            ensure_default_parent()
            if not buffer:
                buffer.append((t, content))
                continue

            prev_text = buffer[-1][1]
            should_split = False

            tentative = "\n\n".join([c for _, c in buffer] + [content])
            tentative_tokens = estimate_tokens(tentative)
            if tentative_tokens > self.max_tokens:
                should_split = True
            else:
                buf_tokens = estimate_tokens("\n\n".join(c for _, c in buffer))
                if buf_tokens >= self.min_tokens_before_sim_split:
                    sim = self._similarity(prev_text, content)
                    if sim < self.sim_threshold:
                        should_split = True

            if should_split:
                flush_buffer()
            buffer.append((t, content))

        flush_buffer()

        raw_count = len(chunks)
        if self._needs_consolidate(chunks):
            chunks = self._consolidate(chunks, parents, document_id)
        self._reindex(chunks, parents)

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

        for _ in range(8):
            packed = self._pack_once(chunks, document_id, pack_limit)
            if len(packed) <= hard_cap:
                return packed
            # Still too many — allow larger packs
            pack_limit = max(pack_limit + 1, int(pack_limit * 1.75))
            chunks = packed
            log.warning(
                "ChunkingService: %s chunks exceed cap %s — repacking with max_tokens=%s",
                len(chunks),
                hard_cap,
                pack_limit,
            )

        # Last resort: force-merge into hard_cap buckets (tables still atomic-ish)
        return self._force_cap(chunks, document_id, hard_cap)

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
