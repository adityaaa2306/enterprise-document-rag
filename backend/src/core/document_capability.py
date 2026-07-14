"""
Document Capability Analyzer.

Produces a size/complexity profile used by adaptive strategy selection.
Does NOT modify structure parsing or heading detection — reads chunk + triage outputs.
"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from src.chunking.service import estimate_tokens

_EQ_RE = re.compile(r"(\$[^$]+\$|\\\(|\\\[|\\begin\{equation\}|∑|∫|=)", re.I)
_CODE_RE = re.compile(r"(```|class\s+\w+\(|def\s+\w+\(|import\s+\w+|SELECT\s+.+\s+FROM)", re.I)
_FIG_RE = re.compile(r"\b(figure|fig\.|diagram|chart|image)\b", re.I)
_TABLE_RE = re.compile(r"(---\s*TABLE|\btable\b|\|.*\|)", re.I)


@dataclass
class DocumentCapabilityProfile:
    pages_estimate: int = 0
    estimated_tokens: int = 0
    semantic_sections: int = 0
    chunk_count: int = 0
    average_section_tokens: float = 0.0
    largest_section_tokens: int = 0
    table_count: int = 0
    figure_count: int = 0
    code_block_count: int = 0
    equation_count: int = 0
    reading_level: float = 0.5  # 0 easy → 1 hard
    technical_density: float = 0.0
    layout_complexity: float = 0.0
    heading_depth: int = 1
    table_density: float = 0.0
    image_density: float = 0.0
    chunk_count_estimate: int = 0
    embedding_complexity: float = 0.0
    document_scale: str = "medium"  # tiny|small|medium|large|xlarge
    complexity_class: str = "moderate"  # simple|moderate|complex|critical
    signals: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _scale_from_tokens(tokens: int, pages: int, chunks: int) -> str:
    # Prefer tokens; pages/chunks as secondary signals
    if tokens < 2500 and pages <= 15 and chunks <= 8:
        return "tiny"
    if tokens < 12000 and pages <= 50 and chunks <= 25:
        return "small"
    if tokens < 60000 and pages <= 200 and chunks <= 80:
        return "medium"
    if tokens < 200000 and pages <= 500 and chunks <= 200:
        return "large"
    return "xlarge"


def _reading_level(text: str) -> float:
    """Heuristic 0–1 reading difficulty (word length + sentence length)."""
    words = re.findall(r"[A-Za-z]{2,}", text)
    if not words:
        return 0.4
    avg_w = sum(len(w) for w in words) / len(words)
    sents = max(1, text.count(".") + text.count("!") + text.count("?"))
    avg_s = len(words) / sents
    # Normalize roughly: avg word 4–8, sentence 12–28
    score = (min(1.0, max(0.0, (avg_w - 4.0) / 4.0)) * 0.5) + (
        min(1.0, max(0.0, (avg_s - 12.0) / 16.0)) * 0.5
    )
    return round(score, 3)


def analyze_document_capability(
    chunks: Sequence[Any],
    *,
    features: Optional[Dict[str, Any]] = None,
    chunk_features: Optional[Sequence[Dict[str, Any]]] = None,
    triage_meta: Optional[Dict[str, Any]] = None,
    chunk_parents: Optional[Sequence[Any]] = None,
) -> DocumentCapabilityProfile:
    features = features or {}
    triage_meta = triage_meta or {}
    chunk_features = list(chunk_features or [])
    sd = triage_meta.get("structure_diagnostics") or {}

    texts: List[str] = []
    for c in chunks:
        if hasattr(c, "content"):
            texts.append(str(c.content or ""))
        elif isinstance(c, dict):
            texts.append(str(c.get("content") or c.get("text") or ""))
        else:
            texts.append(str(c or ""))

    full = "\n\n".join(texts)
    tokens = sum(estimate_tokens(t) for t in texts) or estimate_tokens(full)
    n_chunks = len(chunks)

    # Page estimate: structure diag, or ~500 tokens/page heuristic
    pages = int(sd.get("pages") or features.get("page_count") or 0)
    if pages <= 0:
        pages = max(1, int(math.ceil(tokens / 500.0)))

    section_count = int(
        sd.get("merged_sections")
        or sd.get("semantic_sections")
        or triage_meta.get("section_count")
        or len(chunk_parents or [])
        or max(1, n_chunks)
    )

    sizes = [estimate_tokens(t) for t in texts] or [0]
    avg_sec = float(sum(sizes) / max(1, len(sizes)))
    largest = int(max(sizes))

    table_count = sum(1 for t in texts if _TABLE_RE.search(t[:500]) or "--- TABLE" in t)
    figure_count = sum(1 for t in texts if _FIG_RE.search(t[:400]))
    code_count = sum(1 for t in texts if _CODE_RE.search(t))
    eq_count = sum(len(_EQ_RE.findall(t)) for t in texts)

    tech_vals = [float(f.get("technical_density") or 0) for f in chunk_features]
    tech = (
        sum(tech_vals) / len(tech_vals)
        if tech_vals
        else min(1.0, (eq_count + code_count) / max(1, n_chunks * 2))
    )
    reading = _reading_level(full[:50000])

    layout = float(features.get("layout_complexity") or 0.0)
    if layout <= 0:
        layout = min(
            1.0,
            0.15 * (table_count / max(1, n_chunks))
            + 0.15 * (figure_count / max(1, n_chunks))
            + 0.2 * min(1.0, section_count / 40.0),
        )

    heading_depth = 1
    for c in chunks:
        path = getattr(c, "section_path", None) or (
            c.get("section_path") if isinstance(c, dict) else ""
        )
        if path:
            heading_depth = max(heading_depth, 1 + str(path).count("/"))
    heading_depth = max(heading_depth, int(sd.get("heading_depth") or 1))

    table_density = round(table_count / max(1, n_chunks), 3)
    image_density = round(figure_count / max(1, n_chunks), 3)
    embed_complexity = round(
        min(1.0, 0.4 * tech + 0.3 * reading + 0.3 * min(1.0, tokens / 80000.0)),
        3,
    )

    scale = _scale_from_tokens(tokens, pages, n_chunks)

    reasoning = float(features.get("reasoning_score") or 0.4)
    risk = str(features.get("risk_level") or features.get("domain_label") or "").lower()
    if risk in ("medical", "clinical", "legal") or reasoning >= 0.75 or tech >= 0.75:
        complexity_class = "critical" if risk in ("medical", "clinical") else "complex"
    elif reasoning >= 0.55 or tech >= 0.45 or layout >= 0.5:
        complexity_class = "moderate"
    else:
        complexity_class = "simple"

    profile = DocumentCapabilityProfile(
        pages_estimate=pages,
        estimated_tokens=int(tokens),
        semantic_sections=int(section_count),
        chunk_count=n_chunks,
        average_section_tokens=round(avg_sec, 1),
        largest_section_tokens=largest,
        table_count=table_count,
        figure_count=figure_count,
        code_block_count=code_count,
        equation_count=eq_count,
        reading_level=reading,
        technical_density=round(float(tech), 3),
        layout_complexity=round(float(layout), 3),
        heading_depth=heading_depth,
        table_density=table_density,
        image_density=image_density,
        chunk_count_estimate=n_chunks,
        embedding_complexity=embed_complexity,
        document_scale=scale,
        complexity_class=complexity_class,
        signals={
            "document_type": features.get("document_type"),
            "domain_label": features.get("domain_label"),
            "risk_level": features.get("risk_level"),
            "reasoning_score": reasoning,
            "structural_score": features.get("structural_score"),
            "coherence_score": features.get("coherence_score"),
            "retrieval_confidence": features.get("retrieval_confidence"),
            "validated_headings": sd.get("validated_headings"),
            "rejected_headings": sd.get("rejected_headings"),
            "structure_median_tokens": sd.get("median_chunk_tokens"),
        },
    )
    return profile
