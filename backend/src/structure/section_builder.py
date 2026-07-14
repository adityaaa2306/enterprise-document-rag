"""Build semantic document sections from validated headings + layout blocks."""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Sequence, Tuple

from src.chunking.service import estimate_tokens
from src.structure.types import (
    SECTION_OPENING_CLASSES,
    HeadingDecision,
    LayoutBlock,
    SemanticSection,
)

log = logging.getLogger(__name__)

_EQ_RE = re.compile(r"(\$[^$]+\$|\\\(|\\\[|\\begin\{equation\}|∑|∫)", re.I)
_FIG_RE = re.compile(r"\b(figure|fig\.|diagram|chart)\b", re.I)


def _importance_complexity(text: str, heading_level: int) -> Tuple[float, float]:
    tokens = estimate_tokens(text)
    eqs = len(_EQ_RE.findall(text))
    tech = len(
        re.findall(
            r"\b(algorithm|model|latency|carbon|embedding|protocol|theorem)\b",
            text,
            re.I,
        )
    )
    importance = min(
        1.0,
        0.35 + 0.15 * max(0, 3 - heading_level) + 0.0004 * tokens + 0.05 * min(eqs, 4),
    )
    complexity = min(1.0, 0.25 + 0.08 * min(eqs, 5) + 0.03 * min(tech, 8) + 0.0003 * tokens)
    return round(importance, 3), round(complexity, 3)


def build_semantic_sections(
    blocks: Sequence[LayoutBlock],
    accepted: Sequence[HeadingDecision],
    *,
    document_id: str,
) -> List[SemanticSection]:
    """
    Attach body content to each validated heading until the next opener.
    Non-heading blocks before the first heading form a preamble section.
    Captions / tables / lists attach to the current section (never open new ones).
    """
    by_idx: Dict[int, HeadingDecision] = {d.block_index: d for d in accepted}
    sections: List[SemanticSection] = []
    current: Optional[SemanticSection] = None

    def close():
        nonlocal current
        if current is None:
            return
        current.recount_tokens()
        imp, comp = _importance_complexity(current.body_text(), current.heading_level)
        current.importance = imp
        current.complexity = comp
        if current.body_text().strip():
            sections.append(current)
        current = None

    def open_section(dec: HeadingDecision, block: LayoutBlock) -> None:
        nonlocal current
        close()
        current = SemanticSection(
            section_id=f"{document_id}_sec_{len(sections)}",
            heading=dec.text.strip(),
            heading_level=max(1, int(dec.level or 1)),
            heading_class=dec.classification,  # type: ignore[arg-type]
            page_start=block.page,
            page_end=block.page,
            source_block_indices=[block.index],
        )

    def ensure_preamble(block: LayoutBlock) -> None:
        nonlocal current
        if current is not None:
            return
        current = SemanticSection(
            section_id=f"{document_id}_sec_{len(sections)}",
            heading="Preamble",
            heading_level=1,
            heading_class="major_heading",
            page_start=block.page,
            page_end=block.page,
            source_block_indices=[],
        )

    for block in blocks:
        text = (block.text or "").strip()
        if not text:
            continue

        dec = by_idx.get(block.index)
        if dec and dec.accepted and dec.classification in SECTION_OPENING_CLASSES:
            open_section(dec, block)
            continue

        ensure_preamble(block)
        assert current is not None
        current.source_block_indices.append(block.index)
        if block.page is not None:
            current.page_end = block.page
            if current.page_start is None:
                current.page_start = block.page

        btype = (block.block_type or "Text").lower()
        low = text.lower()
        if btype == "table" or text.startswith("--- TABLE"):
            current.tables.append(text)
        elif btype == "list":
            current.lists.append(text)
        elif _FIG_RE.search(low[:80]) and len(text.split()) <= 30:
            current.captions.append(text)
        elif _EQ_RE.search(text) and len(text) < 400:
            current.equations.append(text)
        else:
            current.paragraphs.append(text)

    close()
    log.info("SectionBuilder: %s semantic sections from %s blocks", len(sections), len(blocks))
    return sections


def sections_to_tree(sections: Sequence[SemanticSection]) -> List[Dict]:
    """Nested outline for developer structure viewer."""
    roots: List[Dict] = []
    stack: List[Dict] = []  # nodes with heading_level

    for sec in sections:
        node = {
            "id": sec.section_id,
            "heading": sec.heading,
            "level": sec.heading_level,
            "tokens": sec.estimated_tokens,
            "children": [],
            "blocks": [],
        }
        for p in sec.paragraphs[:12]:
            node["blocks"].append({"kind": "paragraph", "preview": p[:120]})
        for t in sec.tables:
            node["blocks"].append({"kind": "table", "preview": t[:120]})
        for c in sec.captions:
            node["blocks"].append({"kind": "caption", "preview": c[:120]})
        for e in sec.equations:
            node["blocks"].append({"kind": "equation", "preview": e[:120]})
        for lst in sec.lists:
            node["blocks"].append({"kind": "list", "preview": lst[:120]})

        while stack and stack[-1]["level"] >= sec.heading_level:
            stack.pop()
        if not stack:
            roots.append(node)
        else:
            stack[-1]["children"].append(node)
        stack.append(node)
    return roots
