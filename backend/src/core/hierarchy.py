"""
Section-aware hierarchical summarization helpers.

Adaptive semantic compression for regional grouping:
maximize information preserved, minimize compile calls, respect context windows.
"""
from __future__ import annotations

import logging
import math
import re
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


def _tokenize(text: str) -> set:
    words = re.findall(r"[a-z0-9]{3,}", (text or "").lower())
    return set(words)


def _lexical_jaccard(a: str, b: str) -> float:
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return float(inter) / float(union) if union else 0.0


def _density_score(text: str) -> float:
    """Higher = denser information (more unique tokens per length)."""
    toks = _tokenize(text)
    if not toks:
        return 0.5
    chars = max(1, len(text or ""))
    return min(1.5, len(toks) / (chars / 40.0))


def group_summaries_by_section(
    chunks: Sequence[Any],
    summaries: Sequence[str],
) -> List[Dict[str, Any]]:
    """Legacy section-key grouping (kept for tests / callers). Prefer adaptive."""
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


def group_summaries_adaptive(
    chunks: Sequence[Any],
    summaries: Sequence[str],
    *,
    context_budget: Optional[int] = None,
    capability_score: float = 0.5,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Adaptive regional packing.

    Maximizes semantic compression (fewer regionals) while preserving coherence
    and staying under a share of the compile context budget.

    Signals (no fixed chunk-count target):
      - section continuity (same parent_id / path prefix)
      - lexical similarity (adjacent summaries)
      - token / prompt budget
      - information density (denser → smaller groups)
      - capability_score (higher → slightly larger packs when coherent)
      - latency-aware pack guidance from sqrt(n) (not a hard 4–8 rule)
    """
    from src.core.pipeline_dag import context_token_budget

    budget = int(context_budget or context_token_budget())
    # Regional prompts share context with instructions; keep ~28% for child text
    # (headroom preserves synthesis quality vs packing the full window).
    soft_cap = max(400, int(budget * 0.28))
    cap = max(0.0, min(1.0, float(capability_score or 0.5)))
    soft_cap = int(soft_cap * (0.85 + 0.25 * cap))

    leaves: List[Dict[str, Any]] = []
    for i, chunk in enumerate(chunks):
        if i >= len(summaries):
            break
        text = str(summaries[i] or "").strip()
        if not text:
            continue
        pid, path = _chunk_parent_key(chunk, i)
        leaves.append(
            {
                "index": i,
                "text": text,
                "parent_id": pid,
                "section_path": path,
                "tokens": estimate_tokens(text),
                "density": _density_score(text),
            }
        )

    if not leaves:
        return [], {
            "avg_chunks_per_regional": 0.0,
            "avg_tokens_per_regional": 0.0,
            "compression_ratio": 1.0,
            "regional_count": 0,
            "chunk_count": 0,
            "soft_cap_tokens": soft_cap,
        }

    n_leaves = len(leaves)
    # Latency/quality guidance: prefer enough regionals for a chapter level when
    # the document is non-trivial. Continuous in n — NOT a fixed 4–8 rule.
    # target_regionals ≈ sqrt(n) scaled by capability (higher cap → fewer regionals).
    target_regionals = max(2, int(round(math.sqrt(n_leaves) * (1.25 - 0.35 * cap))))
    if n_leaves <= 3:
        target_regionals = 1
    elif n_leaves <= 6:
        target_regionals = max(2, int(round(n_leaves / 3)))
    soft_max_pack = max(2, int(math.ceil(n_leaves / float(target_regionals))))

    groups: List[Dict[str, Any]] = []
    cur: Dict[str, Any] = {
        "parent_id": leaves[0]["parent_id"],
        "section_path": leaves[0]["section_path"],
        "indices": [leaves[0]["index"]],
        "summaries": [leaves[0]["text"]],
        "token_estimate": leaves[0]["tokens"],
        "density_sum": leaves[0]["density"],
    }

    def _flush() -> None:
        nonlocal cur
        if cur["indices"]:
            groups.append(
                {
                    "parent_id": cur["parent_id"],
                    "section_path": cur["section_path"],
                    "indices": list(cur["indices"]),
                    "summaries": list(cur["summaries"]),
                    "token_estimate": int(cur["token_estimate"]),
                }
            )

    for leaf in leaves[1:]:
        same_section = leaf["parent_id"] == cur["parent_id"]
        path_a = str(cur["section_path"] or "")
        path_b = str(leaf["section_path"] or "")
        path_cont = bool(
            path_a
            and path_b
            and (
                path_a in path_b
                or path_b in path_a
                or path_a.split("/")[0] == path_b.split("/")[0]
            )
        )
        sim = _lexical_jaccard(cur["summaries"][-1], leaf["text"])
        combined = int(cur["token_estimate"]) + int(leaf["tokens"])
        pack_n = len(cur["indices"]) + 1
        avg_density = (float(cur["density_sum"]) + float(leaf["density"])) / pack_n
        # Denser packs stop earlier (preserve detail).
        density_cap = soft_cap * (1.10 - 0.30 * min(1.2, avg_density))
        under_budget = combined <= density_cap
        # Cross-section packs use a tighter token share to preserve coherence.
        if same_section or path_cont:
            token_ok = under_budget
            pack_ok = pack_n <= soft_max_pack + 2  # slight slack for continuous sections
        else:
            token_ok = combined <= soft_cap * (0.45 + 0.15 * cap)
            pack_ok = pack_n <= soft_max_pack
        # Coherence: section affinity, path continuity, or solid lexical overlap.
        coherent = same_section or path_cont or sim >= (0.12 - 0.04 * cap)
        # Document-order soft merge only when still small and similar enough.
        if not coherent and token_ok and pack_n <= max(2, soft_max_pack // 2) and sim >= 0.05:
            coherent = True
        can_merge = coherent and token_ok and pack_ok
        if not can_merge and same_section and combined <= soft_cap and pack_n <= soft_max_pack + 3:
            can_merge = True

        if can_merge:
            cur["indices"].append(leaf["index"])
            cur["summaries"].append(leaf["text"])
            cur["token_estimate"] = combined
            cur["density_sum"] = float(cur["density_sum"]) + float(leaf["density"])
            if same_section:
                cur["parent_id"] = leaf["parent_id"]
                cur["section_path"] = leaf["section_path"]
            elif not str(cur.get("section_path") or "").startswith("adapt/"):
                cur["section_path"] = f"adapt/{cur['section_path']}→{leaf['section_path']}"
                cur["parent_id"] = f"adapt-{cur['indices'][0]}"
        else:
            _flush()
            cur = {
                "parent_id": leaf["parent_id"],
                "section_path": leaf["section_path"],
                "indices": [leaf["index"]],
                "summaries": [leaf["text"]],
                "token_estimate": leaf["tokens"],
                "density_sum": leaf["density"],
            }
    _flush()

    # Split any single group that somehow exceeds full soft_cap (oversized section).
    final: List[Dict[str, Any]] = []
    for g in groups:
        if int(g["token_estimate"]) <= soft_cap or len(g["indices"]) <= 1:
            final.append(g)
            continue
        batch_idx: List[int] = []
        batch_sum: List[str] = []
        tok = 0
        for idx, text in zip(g["indices"], g["summaries"]):
            t = estimate_tokens(text)
            if batch_idx and tok + t > soft_cap:
                final.append(
                    {
                        "parent_id": g["parent_id"],
                        "section_path": g["section_path"],
                        "indices": list(batch_idx),
                        "summaries": list(batch_sum),
                        "token_estimate": tok,
                    }
                )
                batch_idx, batch_sum, tok = [], [], 0
            batch_idx.append(idx)
            batch_sum.append(text)
            tok += t
        if batch_idx:
            final.append(
                {
                    "parent_id": g["parent_id"],
                    "section_path": g["section_path"],
                    "indices": list(batch_idx),
                    "summaries": list(batch_sum),
                    "token_estimate": tok,
                }
            )

    n_chunks = sum(len(g["indices"]) for g in final)
    n_reg = len(final)
    avg_chunks = (n_chunks / n_reg) if n_reg else 0.0
    avg_tok = (
        sum(int(g["token_estimate"]) for g in final) / n_reg if n_reg else 0.0
    )
    diag = {
        "avg_chunks_per_regional": round(avg_chunks, 3),
        "avg_tokens_per_regional": round(avg_tok, 1),
        "compression_ratio": round(n_chunks / max(1, n_reg), 3),
        "regional_count": n_reg,
        "chunk_count": n_chunks,
        "soft_cap_tokens": soft_cap,
        "soft_max_pack": soft_max_pack,
        "target_regionals_guidance": target_regionals,
        "naive_section_groups": len(group_summaries_by_section(chunks, summaries)),
        "compile_reduction_vs_1to1": max(0, n_chunks - n_reg),
    }
    log.info(
        "Adaptive regional: chunks=%s regionals=%s compression=%.2fx avg_chunks=%.2f "
        "soft_cap=%s soft_max_pack=%s target≈%s",
        n_chunks,
        n_reg,
        diag["compression_ratio"],
        avg_chunks,
        soft_cap,
        soft_max_pack,
        target_regionals,
    )
    return final, diag


def build_hierarchy_levels(
    chunks: Sequence[Any],
    summaries: Sequence[str],
    *,
    fan_in: int = 8,
    max_depth: int = 12,
    skip_regional_below: int = 0,
    capability_score: float = 0.5,
    adaptive_regional: bool = True,
) -> List[Dict[str, Any]]:
    """
    Dynamic hierarchy: level-0 = chunk summaries, then adaptive regional merges,
    then recursive fan-in until few nodes remain. Depth is not hardcoded —
    packing continues while node count exceeds fan_in and depth < max_depth.
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
    compression_diag: Dict[str, Any] = {}

    # Level 1: adaptive regional (optional for tiny docs)
    if len(leaf_nodes) < skip_regional_below:
        current = leaf_nodes
        level_idx = 1
        log.info(
            "Hierarchy: skip regional (chunks=%s < skip_below=%s)",
            len(leaf_nodes),
            skip_regional_below,
        )
    else:
        if adaptive_regional:
            regional, compression_diag = group_summaries_adaptive(
                chunks,
                summaries,
                capability_score=capability_score,
            )
        else:
            regional = group_summaries_by_section(chunks, summaries)
            compression_diag = {
                "avg_chunks_per_regional": (
                    len(leaf_nodes) / max(1, len(regional)) if regional else 0.0
                ),
                "compression_ratio": (
                    len(leaf_nodes) / max(1, len(regional)) if regional else 1.0
                ),
                "regional_count": len(regional),
                "chunk_count": len(leaf_nodes),
            }
        region_nodes = []
        for gi, g in enumerate(regional):
            joined = "\n\n".join(g["summaries"])
            # Stable id: prefer parent when single-section, else adaptive index
            rid = (
                f"region-{g['parent_id']}"
                if len(g["indices"]) == 1
                else f"region-adapt-{gi}"
            )
            # Avoid collisions when multiple single-parent groups share parent
            if any(n["id"] == rid for n in region_nodes):
                rid = f"region-adapt-{gi}"
            region_nodes.append(
                {
                    "id": rid,
                    "level": 1,
                    "section_path": g["section_path"],
                    "parent_id": g["parent_id"],
                    "text": joined,
                    "source_indices": list(g["indices"]),
                    "token_estimate": estimate_tokens(joined),
                }
            )
        levels.append({"level": 1, "kind": "regional", "nodes": region_nodes})
        levels[0]["compression_diag"] = compression_diag  # type: ignore[index]
        current = region_nodes
        level_idx = 2

    # Further levels: pack by fan_in (depth chosen dynamically)
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

    if compression_diag:
        levels.append(
            {
                "level": -1,
                "kind": "_diag",
                "nodes": [],
                "compression_diag": compression_diag,
            }
        )
    return [lv for lv in levels if lv.get("kind") != "_diag"]


def hierarchy_diagnostics(levels: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract compression diagnostics attached during build."""
    for lv in levels:
        if lv.get("compression_diag"):
            return dict(lv["compression_diag"])
        if lv.get("kind") == "chunk" and lv.get("compression_diag"):
            return dict(lv["compression_diag"])
    # Derive from levels if missing
    chunks = 0
    regional = 0
    for lv in levels:
        if lv.get("kind") == "chunk":
            chunks = len(lv.get("nodes") or [])
        if lv.get("kind") == "regional":
            regional = len(lv.get("nodes") or [])
            sizes = [len(n.get("source_indices") or []) for n in (lv.get("nodes") or [])]
            avg = (sum(sizes) / len(sizes)) if sizes else 0.0
            return {
                "avg_chunks_per_regional": round(avg, 3),
                "compression_ratio": round(chunks / max(1, regional), 3),
                "regional_count": regional,
                "chunk_count": chunks,
            }
    return {}


def hierarchy_tree_for_ui(levels: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    clean = [lv for lv in levels if lv.get("kind") != "_diag"]
    return {
        "depth": len(clean),
        "compression": hierarchy_diagnostics(levels),
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
            for lv in clean
        ],
    }


def hierarchy_tree_from_frozen_nodes(
    nodes: Dict[str, Any],
    *,
    overflow_ids: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """UI tree from frozen DAG topology (includes overflow)."""
    overflow_set = set(overflow_ids or [])
    by_kind: Dict[str, List[Any]] = {}
    for nid, n in nodes.items():
        kind = getattr(n, "kind", None) or (n.get("kind") if isinstance(n, dict) else None)
        if not kind or kind == "chunk":
            continue
        by_kind.setdefault(str(kind), []).append((nid, n))
    levels = []
    order = ["regional", "chapter", "executive", "final", "compile"]
    seen = set()
    for i, kind in enumerate(order):
        items = by_kind.get(kind) or []
        if not items:
            continue
        seen.add(kind)
        levels.append(
            {
                "level": i + 1,
                "kind": kind,
                "node_count": len(items),
                "overflow_count": sum(
                    1
                    for nid, _ in items
                    if nid in overflow_set or "-ovf-" in str(nid)
                ),
                "nodes": [
                    {
                        "id": nid,
                        "section_path": getattr(n, "section_path", None)
                        or (n.get("section_path") if isinstance(n, dict) else ""),
                        "token_estimate": getattr(n, "token_estimate", None)
                        or (n.get("token_estimate") if isinstance(n, dict) else 0),
                        "source_indices": [],
                        "preview": (
                            str(
                                getattr(n, "output_summary", None)
                                or getattr(n, "input_text", None)
                                or (n.get("output_summary") if isinstance(n, dict) else "")
                                or ""
                            )
                        )[:160],
                        "overflow": nid in overflow_set or "-ovf-" in str(nid),
                    }
                    for nid, n in items[:40]
                ],
            }
        )
    return {"depth": len(levels), "levels": levels, "frozen": True}


def regional_texts_for_compile(levels: Sequence[Dict[str, Any]]) -> List[str]:
    """Prefer last regional/compile level texts for final executive compile."""
    if not levels:
        return []
    for lv in reversed(list(levels)):
        if lv.get("kind") == "_diag":
            continue
        nodes = lv.get("nodes") or []
        if nodes:
            return [str(n.get("text") or "") for n in nodes if str(n.get("text") or "").strip()]
    return []
