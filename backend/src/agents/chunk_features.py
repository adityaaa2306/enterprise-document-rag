"""
Per-chunk feature extraction for adaptive routing.

Runs after adaptive chunking and before map summarization.
No LLM calls required — lexical + optional embedding signals.
"""
from __future__ import annotations

import logging
import math
import re
from typing import Any, Dict, List, Optional, Sequence

from src.chunking.service import estimate_tokens

log = logging.getLogger(__name__)

_EQ_RE = re.compile(
    r"(\$[^$]+\$|\\\(|\\\[|\\begin\{equation\}|\\frac\{|∑|∫|=|≈|≤|≥)",
    re.I,
)
_FIG_RE = re.compile(r"\b(figure|fig\.|image|diagram|chart)\b", re.I)
_TABLE_RE = re.compile(r"\b(table|tabular)\b|\|.*\|", re.I)
_ENTITY_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+|[A-Z]{2,})\b")
_TECH_RE = re.compile(
    r"\b(algorithm|theorem|lemma|hypothesis|methodology|variance|"
    r"gradient|latency|throughput|protocol|api|sql|json|embedding|"
    r"neural|transformer|regression|covariance|optimizer)\b",
    re.I,
)
_LEGAL_RE = re.compile(
    r"\b(pursuant|hereinafter|shall|clause|section\s+\d+|§|plaintiff|defendant)\b",
    re.I,
)


def _content(chunk: Any) -> str:
    if hasattr(chunk, "content"):
        return str(getattr(chunk, "content") or "")
    if isinstance(chunk, dict):
        return str(chunk.get("content") or chunk.get("text") or "")
    return str(chunk or "")


def _section_type(chunk: Any, text: str) -> str:
    kind = getattr(chunk, "chunk_kind", None) or (
        chunk.get("chunk_kind") if isinstance(chunk, dict) else None
    )
    if kind == "table" or _TABLE_RE.search(text[:400]):
        return "table"
    if kind == "list":
        return "list"
    if kind == "title":
        return "heading"
    if _EQ_RE.search(text):
        return "equation_heavy"
    if _LEGAL_RE.search(text):
        return "legal"
    path = getattr(chunk, "section_path", None) or (
        chunk.get("section_path") if isinstance(chunk, dict) else ""
    )
    path_l = str(path or "").lower()
    if any(k in path_l for k in ("appendix", "reference", "bibliography")):
        return "appendix"
    if any(k in path_l for k in ("method", "result", "discussion", "abstract")):
        return "technical"
    return "narrative"


def _heading_level(chunk: Any) -> int:
    path = str(
        getattr(chunk, "section_path", None)
        or (chunk.get("section_path") if isinstance(chunk, dict) else "")
        or ""
    )
    if not path or path == "Document":
        return 0
    return min(6, 1 + path.count("/"))


def _novelty_vs_prev(prev_tokens: set, cur_tokens: set) -> float:
    if not cur_tokens:
        return 0.0
    if not prev_tokens:
        return 1.0
    novel = cur_tokens - prev_tokens
    return len(novel) / max(1, len(cur_tokens))


def extract_chunk_features(
    chunks: Sequence[Any],
    *,
    embeddings: Optional[List[List[float]]] = None,
) -> List[Dict[str, Any]]:
    """
    Compute routing features for every chunk.

    Returns a list aligned with ``chunks`` indices.
    """
    features: List[Dict[str, Any]] = []
    prev_tokens: set = set()
    for i, chunk in enumerate(chunks):
        text = _content(chunk)
        words = re.findall(r"\S+", text)
        word_count = len(words)
        token_count = estimate_tokens(text)
        eq_count = len(_EQ_RE.findall(text))
        table_count = 1 if (
            getattr(chunk, "chunk_kind", None) == "table" or bool(_TABLE_RE.search(text[:500]))
        ) else 0
        fig_count = len(_FIG_RE.findall(text))
        entities = _ENTITY_RE.findall(text)
        entity_density = min(1.0, len(entities) / max(40.0, word_count / 5.0))
        tech_hits = len(_TECH_RE.findall(text))
        technical_density = min(1.0, tech_hits / max(8.0, word_count / 80.0))
        section_type = _section_type(chunk, text)
        heading_level = _heading_level(chunk)

        toks = set(re.findall(r"[a-zA-Z]{3,}", text.lower()))
        novelty = _novelty_vs_prev(prev_tokens, toks)
        prev_tokens |= set(list(toks)[:80])

        # Complexity: length + tech + equations + legal cues
        length_score = min(1.0, token_count / 1200.0)
        complexity = max(
            0.0,
            min(
                1.0,
                0.35 * length_score
                + 0.30 * technical_density
                + 0.20 * min(1.0, eq_count / 5.0)
                + 0.15 * (1.0 if section_type in ("legal", "equation_heavy") else 0.0),
            ),
        )
        # Importance: section type + entities + novelty + early position bias
        position = 1.0 - (i / max(1, len(chunks)))
        importance = max(
            0.0,
            min(
                1.0,
                0.30 * entity_density
                + 0.25 * novelty
                + 0.20 * (1.0 if section_type in ("technical", "legal", "equation_heavy") else 0.4)
                + 0.15 * position
                + 0.10 * min(1.0, table_count + fig_count),
            ),
        )
        compression_difficulty = max(
            0.0,
            min(1.0, 0.5 * complexity + 0.3 * technical_density + 0.2 * entity_density),
        )
        confidence = max(
            0.35,
            min(1.0, 0.7 + 0.2 * (1.0 if word_count > 40 else 0.0) - 0.15 * (1.0 if word_count < 15 else 0.0)),
        )

        emb = None
        if embeddings is not None and i < len(embeddings):
            emb = embeddings[i]

        features.append(
            {
                "chunk_index": i,
                "complexity": round(complexity, 4),
                "importance": round(importance, 4),
                "novelty": round(novelty, 4),
                "confidence": round(confidence, 4),
                "section_type": section_type,
                "named_entity_density": round(entity_density, 4),
                "technical_density": round(technical_density, 4),
                "equation_count": int(eq_count),
                "table_count": int(table_count),
                "figure_count": int(fig_count),
                "heading_level": int(heading_level),
                "word_count": int(word_count),
                "token_count": int(token_count),
                "compression_difficulty": round(compression_difficulty, 4),
                "has_embedding": emb is not None,
                "parent_id": getattr(chunk, "parent_id", None)
                or (chunk.get("parent_id") if isinstance(chunk, dict) else None),
                "section_path": getattr(chunk, "section_path", None)
                or (chunk.get("section_path") if isinstance(chunk, dict) else None),
            }
        )
    return features


def attach_features_to_chunks(
    chunks: List[Any], features: List[Dict[str, Any]]
) -> List[Any]:
    """Best-effort: set ``features`` attribute on AdaptiveChunk-like objects."""
    for i, chunk in enumerate(chunks):
        if i >= len(features):
            break
        feat = features[i]
        if hasattr(chunk, "__dict__") or hasattr(chunk, "model_copy"):
            try:
                if hasattr(chunk, "model_copy"):
                    # pydantic — store via object.__setattr__ for extra
                    object.__setattr__(chunk, "features", feat)
                else:
                    setattr(chunk, "features", feat)
            except Exception:
                pass
        elif isinstance(chunk, dict):
            chunk["features"] = feat
    return chunks
