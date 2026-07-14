"""Semantically safe merge of neighbouring sections."""
from __future__ import annotations

import logging
import re
from typing import Callable, List, Optional, Sequence, Tuple

from src.chunking.service import estimate_tokens
from src.core.config import settings
from src.structure.types import SemanticSection

log = logging.getLogger(__name__)

EmbedFn = Callable[[List[str]], List[List[float]]]

_MAJOR_BOUNDARY = re.compile(
    r"^(?:appendix|references|bibliography|glossary|index|acknowledg|"
    r"chapter\s+\d|part\s+[ivxlcdm\d]|article\s+\d)",
    re.I,
)


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na <= 1e-9 or nb <= 1e-9:
        return 0.0
    return dot / (na * nb)


def _lexical_sim(a: str, b: str) -> float:
    ta = set(re.findall(r"[a-zA-Z]{3,}", (a or "").lower()))
    tb = set(re.findall(r"[a-zA-Z]{3,}", (b or "").lower()))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(1, len(ta | tb))


def _is_hard_boundary(sec: SemanticSection) -> bool:
    h = (sec.heading or "").strip()
    if sec.heading_level <= 1 and _MAJOR_BOUNDARY.match(h):
        return True
    if sec.tables and estimate_tokens("\n".join(sec.tables)) > 200:
        # large tables prefer isolation when alone; still allow merge of tiny ones
        return False
    return False


def _combine(a: SemanticSection, b: SemanticSection, reason: str) -> SemanticSection:
    out = a.model_copy(deep=True)
    # Keep the higher-level (more major) heading as primary label.
    if b.heading_level < a.heading_level:
        out.heading = b.heading
        out.heading_level = b.heading_level
        out.heading_class = b.heading_class
    out.paragraphs = list(a.paragraphs) + (
        [b.heading] if b.heading and b.heading != "Preamble" else []
    ) + list(b.paragraphs)
    out.tables = list(a.tables) + list(b.tables)
    out.figures = list(a.figures) + list(b.figures)
    out.captions = list(a.captions) + list(b.captions)
    out.lists = list(a.lists) + list(b.lists)
    out.equations = list(a.equations) + list(b.equations)
    out.source_block_indices = list(a.source_block_indices) + list(b.source_block_indices)
    if a.page_start is not None or b.page_start is not None:
        starts = [p for p in (a.page_start, b.page_start) if p is not None]
        ends = [p for p in (a.page_end, b.page_end) if p is not None]
        out.page_start = min(starts) if starts else None
        out.page_end = max(ends) if ends else None
    out.merge_reason = reason
    out.recount_tokens()
    out.importance = max(a.importance, b.importance)
    out.complexity = max(a.complexity, b.complexity)
    return out


def merge_sections(
    sections: Sequence[SemanticSection],
    *,
    embed_fn: Optional[EmbedFn] = None,
    target_tokens: Optional[int] = None,
    max_tokens: Optional[int] = None,
    sim_min: Optional[float] = None,
) -> Tuple[List[SemanticSection], List[dict]]:
    """
    Merge neighbours only when semantically safe.
    Never force a global chunk count.
    """
    if not sections:
        return [], []

    target = int(
        target_tokens
        if target_tokens is not None
        else getattr(settings, "STRUCTURE_TARGET_TOKENS", 800) or 800
    )
    max_tok = int(
        max_tokens
        if max_tokens is not None
        else getattr(settings, "STRUCTURE_MAX_TOKENS", 1200) or 1200
    )
    sim_floor = float(
        sim_min
        if sim_min is not None
        else getattr(settings, "STRUCTURE_MERGE_SIM_MIN", 0.28) or 0.28
    )

    events: List[dict] = []
    current = list(sections)
    changed = True
    guard = 0

    # Batch-embed all section bodies once per pass when possible (same sim math)
    def _sims_for_pairs(
        pairs: List[Tuple[str, str]],
    ) -> List[float]:
        lexical = [_lexical_sim(a, b) for a, b in pairs]
        if embed_fn is None or not pairs:
            return lexical
        try:
            flat: List[str] = []
            for a, b in pairs:
                flat.append(a)
                flat.append(b)
            vecs = embed_fn(flat)
            out = []
            for i, (a, b) in enumerate(pairs):
                base = lexical[i]
                vi = 2 * i
                if vi + 1 < len(vecs):
                    base = max(base, _cosine(vecs[vi], vecs[vi + 1]))
                out.append(base)
            return out
        except Exception as e:
            log.debug("merge batch embed failed: %s", e)
            return lexical

    while changed and guard < 500:
        guard += 1
        changed = False
        # First pass: collect candidate neighbour pairs that need similarity
        candidates: List[Tuple[int, SemanticSection, SemanticSection]] = []
        pair_texts: List[Tuple[str, str]] = []
        i = 0
        scan = list(current)
        while i < len(scan):
            a = scan[i]
            if i + 1 >= len(scan):
                break
            b = scan[i + 1]
            a.recount_tokens()
            b.recount_tokens()
            combined = a.estimated_tokens + b.estimated_tokens
            if _is_hard_boundary(b) or combined > max_tok:
                i += 1
                continue
            if a.estimated_tokens >= target and b.estimated_tokens >= target:
                i += 1
                continue
            text_a = a.body_text()[:2000]
            text_b = b.body_text()[:2000]
            candidates.append((i, a, b))
            pair_texts.append((text_a, text_b))
            i += 1

        sims = _sims_for_pairs(pair_texts)
        sim_by_index = {cand[0]: sims[j] for j, cand in enumerate(candidates)}

        out: List[SemanticSection] = []
        i = 0
        while i < len(current):
            a = current[i]
            if i + 1 >= len(current):
                out.append(a)
                break
            b = current[i + 1]
            a.recount_tokens()
            b.recount_tokens()
            combined = a.estimated_tokens + b.estimated_tokens

            reason = None
            if _is_hard_boundary(b):
                reason = None
            elif combined > max_tok:
                reason = None
            elif a.estimated_tokens >= target and b.estimated_tokens >= target:
                reason = None
            else:
                same_topic = abs(a.heading_level - b.heading_level) <= 1
                sim = float(sim_by_index.get(i, _lexical_sim(a.body_text()[:2000], b.body_text()[:2000])))
                undersized = a.estimated_tokens < target or b.estimated_tokens < target
                if undersized and combined <= max_tok and same_topic and sim >= sim_floor:
                    reason = (
                        f"semantic_merge sim={sim:.3f} combined={combined} "
                        f"<max={max_tok} levels={a.heading_level}/{b.heading_level}"
                    )
                elif (
                    undersized
                    and combined <= max_tok
                    and a.estimated_tokens < 200
                    and b.estimated_tokens < 200
                    and sim >= max(0.15, sim_floor - 0.1)
                ):
                    reason = (
                        f"tiny_section_merge sim={sim:.3f} "
                        f"a={a.estimated_tokens} b={b.estimated_tokens}"
                    )

            if reason:
                merged = _combine(a, b, reason)
                events.append(
                    {
                        "left": a.section_id,
                        "right": b.section_id,
                        "reason": reason,
                        "tokens_after": merged.estimated_tokens,
                    }
                )
                out.append(merged)
                i += 2
                changed = True
            else:
                out.append(a)
                i += 1
        current = out

    log.info(
        "SemanticMerge: %s → %s sections (%s merges)",
        len(sections),
        len(current),
        len(events),
    )
    return current, events
