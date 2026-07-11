import logging
import os
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

# unstructured is the core of our "Triage" (visual chunking) agent
from unstructured.partition.auto import partition
from unstructured.documents.elements import (
    Element,
    Title,
    NarrativeText,
    Table,
    ListItem,
    Text,
    CompositeElement,
)

log = logging.getLogger(__name__)


class Chunk(BaseModel):
    """
    A single "smart chunk" of the document.
    It contains the text content and its semantic type.
    """

    id: str = Field(..., description="The unique ID for this chunk (e.g., doc_XYZ_chunk_0)")
    document_id: str = Field(..., description="The ID of the document this chunk belongs to")
    chunk_index: int = Field(..., description="The order of this chunk in the document")
    type: Literal["Title", "Text", "Table", "List", "Other"] = Field(
        ..., description="The semantic type of the chunk"
    )
    content: str = Field(..., description="The actual text content of the chunk")


def _document_id_from_path(file_path: str) -> str:
    base = os.path.basename(file_path)
    # scratch files are "{job_id}_{original_filename}"
    if "_" in base:
        return base.split("_", 1)[0]
    return os.path.splitext(base)[0] or "doc"


def _element_content(el: Element) -> tuple[Literal["Title", "Text", "Table", "List", "Other"], str]:
    """
    Map any unstructured element to (type, content).

    Important: strategy=fast often yields ``Text`` / ``CompositeElement``, not
    ``NarrativeText``. Older code ignored those and produced zero chunks.
    """
    raw_text = (getattr(el, "text", None) or "").strip()

    if isinstance(el, Title):
        return "Title", raw_text

    if isinstance(el, ListItem):
        return "List", raw_text

    if isinstance(el, Table):
        html = ""
        meta = getattr(el, "metadata", None)
        if meta is not None:
            html = (getattr(meta, "text_as_html", None) or "").strip()
        parts = ["--- TABLE START ---"]
        if html:
            parts.append(f"HTML:\n{html}")
        if raw_text:
            parts.append(f"TEXT:\n{raw_text}")
        parts.append("--- TABLE END ---")
        content = "\n\n".join(parts) if (html or raw_text) else ""
        return "Table", content

    if isinstance(el, (NarrativeText, Text, CompositeElement)):
        return "Text", raw_text

    # Catch-all: Address, EmailAddress, Header, Footer, FigureCaption, etc.
    return "Other", raw_text


def _elements_to_chunks(elements: List[Element], document_id: str) -> List[Chunk]:
    chunks: List[Chunk] = []
    chunk_index = 0
    skipped_empty = 0

    for el in elements:
        chunk_type, content = _element_content(el)
        if not content.strip():
            skipped_empty += 1
            continue
        chunks.append(
            Chunk(
                id=f"{document_id}_chunk_{chunk_index}",
                document_id=document_id,
                chunk_index=chunk_index,
                type=chunk_type,
                content=content,
            )
        )
        chunk_index += 1

    if skipped_empty:
        log.info(
            "Triage: skipped %s empty element(s); kept %s chunk(s)",
            skipped_empty,
            len(chunks),
        )
    return chunks


def _partition_safe(
    file_path: str,
    *,
    content_type: Optional[str],
    strategy: str,
) -> List[Element]:
    kwargs = {"filename": file_path, "strategy": strategy}
    # Wrong/missing MIME can make unstructured return nothing — try with and without.
    if content_type and content_type not in ("application/octet-stream", "binary/octet-stream"):
        kwargs["content_type"] = content_type
    return list(partition(**kwargs) or [])


def _plain_text_fallback(file_path: str, document_id: str) -> List[Chunk]:
    """Last resort for .txt/.md/.csv or when partition yields nothing usable."""
    try:
        with open(file_path, "rb") as f:
            raw = f.read(2_000_000)
        if not raw:
            return []
        # Skip obvious binary (NUL in first 1KB)
        sample = raw[:1024]
        if b"\x00" in sample:
            return []
        text = raw.decode("utf-8", errors="ignore").strip()
        if not text:
            return []
        # Split into rough paragraphs so CRE/summarize still have structure
        parts = [p.strip() for p in text.split("\n\n") if p.strip()]
        if not parts:
            parts = [text]
        chunks: List[Chunk] = []
        for i, part in enumerate(parts[:200]):
            chunks.append(
                Chunk(
                    id=f"{document_id}_chunk_{i}",
                    document_id=document_id,
                    chunk_index=i,
                    type="Text",
                    content=part[:20000],
                )
            )
        log.warning(
            "Triage: using plain-text fallback (%s chunk(s)) for %s",
            len(chunks),
            file_path,
        )
        return chunks
    except Exception as e:
        log.error("Plain-text fallback failed for %s: %s", file_path, e)
        return []


def triage_document(file_path: str, file_type: str, strategy: str) -> List[Chunk]:
    """
    Visual / layout-aware document partition → list of Chunk objects.

    Always attempts to recover text from every element type. Falls back to
    plain-text extraction when unstructured returns nothing usable.
    """
    log.info("Triaging document: %s (strategy=%s, content_type=%s)", file_path, strategy, file_type)
    document_id = _document_id_from_path(file_path)

    if not os.path.isfile(file_path):
        log.error("Triage: file does not exist: %s", file_path)
        return []

    size = os.path.getsize(file_path)
    if size <= 0:
        log.error("Triage: file is empty: %s", file_path)
        return []
    log.info("Triage: file size=%s bytes", size)

    elements: List[Element] = []
    strategies = [strategy or "fast"]
    if strategies[0] != "fast":
        strategies.append("fast")

    last_error: Optional[Exception] = None
    for strat in strategies:
        try:
            elements = _partition_safe(file_path, content_type=file_type, strategy=strat)
            log.info("Triage: partition strategy=%s → %s element(s)", strat, len(elements))
            if elements:
                break
            # Retry without content_type if MIME may be wrong
            elements = _partition_safe(file_path, content_type=None, strategy=strat)
            log.info(
                "Triage: partition strategy=%s (no content_type) → %s element(s)",
                strat,
                len(elements),
            )
            if elements:
                break
        except Exception as e:
            last_error = e
            log.error("Triage: partition failed strategy=%s: %s", strat, e)

    chunks = _elements_to_chunks(elements, document_id) if elements else []

    if not chunks:
        log.warning(
            "Triage: no usable chunks after partition (last_error=%s) — trying plain-text fallback",
            last_error,
        )
        chunks = _plain_text_fallback(file_path, document_id)

    log.info("Triage complete. Extracted %s smart chunks.", len(chunks))
    return chunks
