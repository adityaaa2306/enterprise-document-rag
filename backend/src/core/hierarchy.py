"""
Section-aware hierarchical summarization helpers.

Groups chunk summaries by parent/section, builds dynamic regional levels,
and supports medium-first final compile.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.chunking.service import estimate_tokens

log = logging.getLogger(__name__)


def _chunk_parent_key(chunk: Any, idx: int) -> Tuple[str, str]:
    parent_id = getattr(chunk, "parent_id", None)
    section_path = getattr(chunk, "section_path", None)
    if isinstance(chunk, dict):
        parent_id = parent_id or chunk.get("parent_id")
        section_path = section_path or chunk.get("section_path")
    pid = str(parent_id or f"section_{idx}")
    path = str(section_path or pid)
    return pid, path


def group_summaries_by_section(
    chunks: Sequence[Any],
    summaries: Sequence[str],
) -> List[Dict[str, Any]]:
    """Return regional groups with member indices and concatenated text."""
    groups: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for i, chunk in enumerate(chunks):
        if i >= len(summaries):
            break
        text = str(summaries[i] or "").strip()
        if not text:
            continue
        pid, path = _chunk_parent_key(chunk, i)
        if pid not in groups:
            groups[pid] = {
                "parent_id": pid,
                "section_path": path,
                "indices": [],
                "summaries": [],
                "token_estimate": 0,
            }
            order.append(pid)
        groups[pid]["indices"].append(i)
        groups[pid]["summaries"].append(text)
        groups[pid]["token_estimate"] += estimate_tokens(text)
    return [groups[k] for k in order]


def build_hierarchy_levels(
    chunks: Sequence[Any],
    summaries: Sequence[str],
    *,
    fan_in: int = 8,
    max_depth: int = 12,
    skip_regional_below: int = 0,
) -> List[Dict[str, Any]]:
    """
    Dynamic hierarchy: level-0 = chunk summaries, then regional merges by section,
    then recursive fan-in until few nodes remain.

    Adaptive knobs (from Pipeline Intelligence strategy):
    - fan_in: compile batch width
    - max_depth: hard cap on levels
    - skip_regional_below: if chunk count < N, skip regional and fan-in from leaves
    """
    levels: List[Dict[str, Any]] = []
    leaf_nodes = []
    for i, s in enumerate(summaries):
        if not str(s or "").strip():
            continue
        pid, path = _chunk_parent_key(chunks[i] if i < len(chunks) else {}, i)
        leaf_nodes.append(
            {
                "id": f"chunk-{i}",
                "level": 0,
                "section_path": path,
                "parent_id": pid,
                "text": str(s),
                "source_indices": [i],
                "token_estimate": estimate_tokens(str(s)),
            }
        )
    levels.append({"level": 0, "kind": "chunk", "nodes": leaf_nodes})

    fan_in = max(2, int(fan_in or 8))
    max_depth = max(2, int(max_depth or 12))
    skip_regional_below = max(0, int(skip_regional_below or 0))

    # Level 1: regional by parent_id (optional for tiny docs)
    if len(leaf_nodes) < skip_regional_below:
        current = leaf_nodes
        level_idx = 1
        log.info(
            "Hierarchy: skip regional (chunks=%s < skip_below=%s)",
            len(leaf_nodes),
            skip_regional_below,
        )
    else:
        regional = group_summaries_by_section(chunks, summaries)
        region_nodes = []
        for g in regional:
            joined = "\n\n".join(g["summaries"])
            region_nodes.append(
                {
                    "id": f"region-{g['parent_id']}",
                    "level": 1,
                    "section_path": g["section_path"],
                    "parent_id": g["parent_id"],
                    "text": joined,
                    "source_indices": list(g["indices"]),
                    "token_estimate": estimate_tokens(joined),
                }
            )
        levels.append({"level": 1, "kind": "regional", "nodes": region_nodes})
        current = region_nodes
        level_idx = 2

    # Further levels: pack by fan_in
    while len(current) > max(1, fan_in) and level_idx < max_depth:
        packed = []
        kind = "chapter" if level_idx == 2 else "compile"
        for start in range(0, len(current), fan_in):
            batch = current[start : start + fan_in]
            joined = "\n\n".join(n["text"] for n in batch)
            idxs: List[int] = []
            for n in batch:
                idxs.extend(n.get("source_indices") or [])
            packed.append(
                {
                    "id": f"L{level_idx}-{start // fan_in}",
                    "level": level_idx,
                    "section_path": f"{kind}_level_{level_idx}",
                    "parent_id": None,
                    "text": joined,
                    "source_indices": idxs,
                    "token_estimate": estimate_tokens(joined),
                }
            )
        levels.append({"level": level_idx, "kind": kind, "nodes": packed})
        current = packed
        level_idx += 1

    return levels


def hierarchy_tree_for_ui(levels: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "depth": len(levels),
        "levels": [
            {
                "level": lv.get("level"),
                "kind": lv.get("kind"),
                "node_count": len(lv.get("nodes") or []),
                "nodes": [
                    {
                        "id": n.get("id"),
                        "section_path": n.get("section_path"),
                        "token_estimate": n.get("token_estimate"),
                        "source_indices": n.get("source_indices"),
                        "preview": (n.get("text") or "")[:160],
                    }
                    for n in (lv.get("nodes") or [])[:40]
                ],
            }
            for lv in levels
        ],
    }


def regional_texts_for_compile(levels: Sequence[Dict[str, Any]]) -> List[str]:
    """Prefer last regional/compile level texts for final executive compile."""
    if not levels:
        return []
    # Use the highest level with nodes
    for lv in reversed(list(levels)):
        nodes = lv.get("nodes") or []
        if nodes:
            return [str(n.get("text") or "") for n in nodes if str(n.get("text") or "").strip()]
    return []
