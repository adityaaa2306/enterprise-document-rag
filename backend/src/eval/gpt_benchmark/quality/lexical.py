"""Stdlib lexical metrics — no embedding models, no API calls."""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import List, Set


_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?", re.I)


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall((text or "").lower())


def token_set(text: str) -> Set[str]:
    return set(tokenize(text))


def clamp_score(value: float) -> float:
    if value != value:  # NaN
        return 0.0
    return float(max(0.0, min(100.0, value)))


def exact_match_score(reference: str, candidate: str) -> float:
    return 100.0 if normalize_text(reference) == normalize_text(candidate) else 0.0


def lexical_similarity_score(reference: str, candidate: str) -> float:
    """
    Lexical similarity via SequenceMatcher + token F1 (stdlib only).

    This is intentionally *not* embedding cosine similarity. A future
    SemanticSimilarityEvaluator can plug into the registry without changing
    the BenchmarkEvaluator interface.
    """
    ref = normalize_text(reference)
    cand = normalize_text(candidate)
    if not ref and not cand:
        return 100.0
    if not ref or not cand:
        return 0.0
    seq = SequenceMatcher(None, ref, cand).ratio() * 100.0
    rt, ct = token_set(ref), token_set(cand)
    if not rt and not ct:
        f1 = 100.0
    elif not rt or not ct:
        f1 = 0.0
    else:
        inter = len(rt & ct)
        prec = inter / max(1, len(ct))
        rec = inter / max(1, len(rt))
        f1 = (2 * prec * rec / max(1e-9, prec + rec)) * 100.0
    return clamp_score(0.45 * seq + 0.55 * f1)


def token_recall_score(reference: str, candidate: str) -> float:
    """Share of reference tokens covered by the candidate (completeness proxy)."""
    rt, ct = token_set(reference), token_set(candidate)
    if not rt:
        return 100.0 if not ct else 50.0
    if not ct:
        return 0.0
    return clamp_score(100.0 * len(rt & ct) / len(rt))


def length_ratio_score(reference: str, candidate: str) -> float:
    """
    Conciseness / length alignment vs reference.
    Score peaks near length ratio ≈ 1.0; collapses for empty candidates.
    """
    rlen = len(tokenize(reference)) or len(normalize_text(reference))
    clen = len(tokenize(candidate)) or len(normalize_text(candidate))
    if rlen <= 0 and clen <= 0:
        return 100.0
    if clen <= 0:
        return 0.0
    if rlen <= 0:
        # No reference length — mild preference for short-but-nonempty answers
        return clamp_score(100.0 - min(80.0, clen * 2.0))
    ratio = clen / float(rlen)
    # Ideal band 0.6–1.4
    if 0.6 <= ratio <= 1.4:
        return 100.0
    if ratio < 0.6:
        return clamp_score(100.0 * (ratio / 0.6))
    # Too long
    return clamp_score(100.0 * (1.4 / ratio))


def grounding_score(candidate: str, context: str) -> float:
    """
    Groundedness via context token overlap + simple citation markers.
    If no context, returns None-equivalent via caller (we return -1 sentinel).
    """
    if not (context or "").strip():
        return -1.0
    ct = token_set(candidate)
    if not ct:
        return 0.0
    ctx = token_set(context)
    if not ctx:
        return 0.0
    overlap = len(ct & ctx) / max(1, len(ct))
    citation_bonus = 0.0
    low = (candidate or "").lower()
    if any(m in low for m in ("[", "source", "according to", "as stated", "cited")):
        citation_bonus = 0.08
    # Also reward multi-word phrases appearing in context
    cand_norm = normalize_text(candidate)
    ctx_norm = normalize_text(context)
    phrase_hits = 0
    words = tokenize(candidate)
    for i in range(len(words) - 2):
        phrase = " ".join(words[i : i + 3])
        if phrase in ctx_norm:
            phrase_hits += 1
    phrase_bonus = min(0.15, phrase_hits * 0.03)
    return clamp_score(100.0 * min(1.0, overlap + citation_bonus + phrase_bonus))
