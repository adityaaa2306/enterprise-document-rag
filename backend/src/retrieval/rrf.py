"""Reciprocal Rank Fusion (Phase 2.B)."""
from __future__ import annotations

from typing import Dict, List, Sequence, Tuple


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[str]],
    k: int = 60,
    top_n: int | None = None,
) -> List[Tuple[str, float]]:
    """
    Fuse multiple ranked id lists via RRF.

    score(d) = sum_i 1 / (k + rank_i(d))
    """
    scores: Dict[str, float] = {}
    for ranking in ranked_lists:
        for rank, doc_id in enumerate(ranking):
            if not doc_id:
                continue
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    if top_n is not None:
        return ordered[:top_n]
    return ordered
