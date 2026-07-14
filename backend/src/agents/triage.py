import logging
import os
import re
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

_HEADING_NUMBERED = re.compile(
    r"^(?:(?:chapter|section|part)\s+)?\d+(?:\.\d+)*\.?\s+\S+",
    re.IGNORECASE,
)
_HEADING_MARKDOWN = re.compile(r"^#{1,3}\s+\S+")


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


def _original_name(file_path: str) -> str:
    base = os.path.basename(file_path)
    if "_" in base:
        return base.split("_", 1)[1]
    return base


def _ext(file_path: str) -> str:
    return os.path.splitext(_original_name(file_path))[1].lower()


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


def _looks_like_heading(line: str) -> bool:
    """Heuristic title detection for PDF/plain-text fallbacks (no layout model)."""
    s = (line or "").strip()
    if not s or len(s) < 4 or len(s) > 100:
        return False
    if s.endswith((".", ",", ";")):
        return False
    if _HEADING_MARKDOWN.match(s) or _HEADING_NUMBERED.match(s):
        return True
    words = s.split()
    if len(words) > 14:
        return False
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return False
    upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
    if upper_ratio >= 0.78 and len(s) <= 80:
        return True
    # Title Case short lines (e.g. "Retrieval Techniques")
    if (
        len(words) <= 10
        and all(w[:1].isupper() for w in words if w[:1].isalpha())
        and not s.endswith(".")
    ):
        return True
    return False


def _append_chunk(
    chunks: List[Chunk],
    *,
    document_id: str,
    chunk_type: str,
    content: str,
) -> None:
    content = (content or "").strip()
    if not content:
        return
    chunks.append(
        Chunk(
            id=f"{document_id}_chunk_{len(chunks)}",
            document_id=document_id,
            chunk_index=len(chunks),
            type=chunk_type,  # type: ignore[arg-type]
            content=content[:20000],
        )
    )


def _texts_to_chunks(texts: List[str], document_id: str, *, source: str) -> List[Chunk]:
    """
    Convert plain text pages/blocks into layout Text chunks.

    Heading detection is intentionally NOT applied here. The structure parser
    validates headings with a multi-signal confidence model. Emitting Title for
    every Title-Case line was the root cause of 200+ false sections.
    """
    chunks: List[Chunk] = []
    for part in texts[:200]:
        content = (part or "").strip()
        if not content:
            continue
        # Keep page text intact (newlines preserved) so the structure parser
        # can score line-level heading candidates with whitespace context.
        _append_chunk(
            chunks,
            document_id=document_id,
            chunk_type="Text",
            content=content[:20000],
        )
    if chunks:
        log.info(
            "Triage: %s produced %s layout text block(s) (heading validation deferred)",
            source,
            len(chunks),
        )
    return chunks


def _elements_to_chunks(elements: List[Element], document_id: str) -> List[Chunk]:
    chunks: List[Chunk] = []
    skipped_empty = 0

    for el in elements:
        chunk_type, content = _element_content(el)
        if not content.strip():
            skipped_empty += 1
            continue
        chunks.append(
            Chunk(
                id=f"{document_id}_chunk_{len(chunks)}",
                document_id=document_id,
                chunk_index=len(chunks),
                type=chunk_type,
                content=content,
            )
        )

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


def _pypdf_fallback(file_path: str, document_id: str) -> List[Chunk]:
    """
    Reliable PDF text extraction when unstructured returns nothing.

    This path does NOT use NVIDIA NIM / embeddings — local PyPDF2 only.
    """
    try:
        from PyPDF2 import PdfReader
    except Exception as e:
        log.error("PyPDF2 unavailable: %s", e)
        return []

    try:
        reader = PdfReader(file_path)
        pages: List[str] = []
        for i, page in enumerate(reader.pages):
            try:
                text = (page.extract_text() or "").strip()
            except Exception as pe:
                log.warning("PyPDF2 page %s extract failed: %s", i, pe)
                text = ""
            if text:
                pages.append(text)
        if not pages:
            log.warning(
                "Triage: PyPDF2 found %s page(s) but no extractable text "
                "(likely scanned/image PDF) for %s",
                len(reader.pages),
                file_path,
            )
            return []
        return _texts_to_chunks(pages, document_id, source="pypdf_fallback")
    except Exception as e:
        log.error("Triage: PyPDF2 fallback failed for %s: %s", file_path, e)
        return []


def _docx_fallback(file_path: str, document_id: str) -> List[Chunk]:
    """Extract paragraphs from .docx without unstructured."""
    try:
        import zipfile
        from xml.etree import ElementTree as ET

        with zipfile.ZipFile(file_path) as zf:
            xml = zf.read("word/document.xml")
        root = ET.fromstring(xml)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paras = []
        for node in root.findall(".//w:p", ns):
            texts = [t.text for t in node.findall(".//w:t", ns) if t.text]
            line = "".join(texts).strip()
            if line:
                paras.append(line)
        return _texts_to_chunks(paras, document_id, source="docx_fallback")
    except Exception as e:
        log.error("Triage: docx fallback failed for %s: %s", file_path, e)
        return []


def _plain_text_fallback(file_path: str, document_id: str) -> List[Chunk]:
    """Last resort for .txt/.md/.csv or when partition yields nothing usable."""
    try:
        with open(file_path, "rb") as f:
            raw = f.read(2_000_000)
        if not raw:
            return []
        # Skip obvious binary (NUL in first 1KB) — PDFs should use PyPDF2 instead
        sample = raw[:1024]
        if b"\x00" in sample:
            return []
        text = raw.decode("utf-8", errors="ignore").strip()
        if not text:
            return []
        parts = [p.strip() for p in text.split("\n\n") if p.strip()]
        if not parts:
            parts = [text]
        return _texts_to_chunks(parts, document_id, source="plain_text_fallback")
    except Exception as e:
        log.error("Plain-text fallback failed for %s: %s", file_path, e)
        return []


def _format_fallbacks(file_path: str, document_id: str) -> List[Chunk]:
    ext = _ext(file_path)
    log.info("Triage: running format fallbacks for ext=%s name=%s", ext, _original_name(file_path))

    if ext == ".pdf" or ext == "":
        # Also try PDF if extension missing but file looks like PDF
        chunks = _pypdf_fallback(file_path, document_id)
        if chunks:
            return chunks
        # Detect PDF magic
        try:
            with open(file_path, "rb") as f:
                magic = f.read(5)
            if magic.startswith(b"%PDF") and ext != ".pdf":
                chunks = _pypdf_fallback(file_path, document_id)
                if chunks:
                    return chunks
        except Exception:
            pass

    if ext in (".docx",):
        chunks = _docx_fallback(file_path, document_id)
        if chunks:
            return chunks

    if ext in (".txt", ".md", ".csv", ".json", ".log", ""):
        chunks = _plain_text_fallback(file_path, document_id)
        if chunks:
            return chunks

    # Final attempt: plain text even for unknown types (may no-op on binary)
    return _plain_text_fallback(file_path, document_id)


def triage_document(file_path: str, file_type: str, strategy: str) -> List[Chunk]:
    """
    Document → Chunk list.

    Pipeline (no NVIDIA NIM / embeddings here):
      1. unstructured.partition (layout-aware)
      2. Format-specific fallbacks (PyPDF2 for PDF, zip/xml for DOCX, utf-8 for text)

    NVIDIA NIM is only used later (feature classification, summarize, embed).
    """
    log.info(
        "Triaging document: %s (strategy=%s, content_type=%s)",
        file_path,
        strategy,
        file_type,
    )
    document_id = _document_id_from_path(file_path)

    if not os.path.isfile(file_path):
        log.error("Triage: file does not exist: %s", file_path)
        return []

    size = os.path.getsize(file_path)
    if size <= 0:
        log.error("Triage: file is empty: %s", file_path)
        return []
    log.info(
        "Triage: file size=%s bytes ext=%s original=%s",
        size,
        _ext(file_path),
        _original_name(file_path),
    )

    # PDFs: prefer PyPDF2 first. On Render's slim image, unstructured often
    # crashes with ``libGL.so.1: cannot open shared object file`` (OpenCV).
    # This path does not use NVIDIA NIM or embeddings.
    ext = _ext(file_path)
    if ext == ".pdf":
        pdf_chunks = _pypdf_fallback(file_path, document_id)
        if pdf_chunks:
            log.info("Triage complete via PyPDF2. Extracted %s chunks.", len(pdf_chunks))
            return pdf_chunks
        log.warning("Triage: PyPDF2 returned no text; trying unstructured next")

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
            "Triage: unstructured produced no usable chunks (elements=%s last_error=%s) "
            "— trying format fallbacks (PyPDF2/docx/text). NOT an NIM/API-key issue.",
            len(elements),
            last_error,
        )
        chunks = _format_fallbacks(file_path, document_id)

    log.info("Triage complete. Extracted %s smart chunks.", len(chunks))
    return chunks
