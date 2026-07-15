"""
Unified pipeline DAG: chunk → regional → chapter → executive → final.

Map and compile nodes share one schema and one MAX_PARALLEL_WORKERS capacity pool.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from src.chunking.service import estimate_tokens
from src.core import hierarchy as hierarchy_mod
from src.core.config import settings

log = logging.getLogger(__name__)

ProgressCb = Optional[Callable[[float, str, Dict[str, Any]], None]]

# Monotonic counter so overflow node ids never collide on re-insert.
_OVERFLOW_SEQ = 0

# Planning-phase gate: ensure_prompt_budget may mutate topology ONLY while True.
# Execution must never flip this; frozen DAGs raise if budget insert is attempted.
_PLANNING_OVERFLOW_ALLOWED = False


def allow_planning_overflow(enabled: bool = True) -> None:
    """Enable/disable topology mutation via ensure_prompt_budget (planning only)."""
    global _PLANNING_OVERFLOW_ALLOWED
    _PLANNING_OVERFLOW_ALLOWED = bool(enabled)


def planning_overflow_allowed() -> bool:
    return bool(_PLANNING_OVERFLOW_ALLOWED)


def _next_overflow_id(parent_id: str, batch_index: int) -> str:
    global _OVERFLOW_SEQ
    _OVERFLOW_SEQ += 1
    return f"{parent_id}-ovf-{batch_index}-{_OVERFLOW_SEQ}"


def _expected_summary_token_cap(dep_count: int) -> int:
    """Cap for a pending child summary when estimating parent compile size."""
    budget = context_token_budget()
    return max(64, budget // max(4, int(dep_count) or 1))


def estimate_compile_prompt_tokens(
    nodes: Dict[str, DagNode], n: DagNode
) -> Tuple[int, str]:
    """
    Tokens the node will send once deps are ready.

    Pending non-chunk deps contribute a capped summary-sized estimate — not their
    full input_text — so we do not falsely overflow parents and re-insert layers.
    """
    parts: List[str] = []
    est = 0
    dep_n = max(1, len(n.dep_ids))
    cap = _expected_summary_token_cap(dep_n)
    for d in n.dep_ids:
        child = nodes.get(d)
        if not child:
            continue
        summary = str(child.output_summary or "").strip()
        if summary:
            parts.append(summary)
            est += estimate_tokens(summary)
            continue
        if child.kind == "chunk":
            text = str(child.output_summary or child.input_text or "")
            if text:
                parts.append(text)
                est += estimate_tokens(text)
            continue
        # Pending intermediate: will emit a summary, not its full prompt input.
        child_est = int(child.token_estimate or 0)
        est += min(child_est, cap) if child_est > 0 else min(cap, 256)
    return est, "\n\n".join(parts)


@dataclass
class DagNode:
    """Full node schema for the unified document processing graph."""

    id: str
    kind: str  # chunk|regional|chapter|executive|final
    depth: int
    dep_ids: List[str] = field(default_factory=list)
    parent_ids: List[str] = field(default_factory=list)
    children_ids: List[str] = field(default_factory=list)
    status: str = "pending"  # pending|ready|running|completed|failed|retrying
    assigned_model: Optional[str] = None
    endpoint_id: Optional[str] = None
    worker_id: Optional[str] = None
    carbon_estimate_g: float = 0.0
    energy_kwh: float = 0.0
    latency_ms: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    retries: int = 0
    input_text: str = ""
    output_summary: str = ""
    section_path: str = ""
    token_estimate: int = 0
    qva_confidence: float = 0.0
    used_heavy: bool = False
    tier: Optional[str] = None
    chunk_index: Optional[int] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    queue_wait_ms: float = 0.0
    cancel_requested: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def context_token_budget() -> int:
    window = int(getattr(settings, "COMPILE_CONTEXT_WINDOW_TOKENS", 12000) or 12000)
    frac = float(getattr(settings, "COMPILE_PROMPT_MAX_CONTEXT_FRAC", 0.80) or 0.80)
    soft = int(getattr(settings, "COMPILE_MAX_INPUT_TOKENS", 10000) or 10000)
    return max(1000, min(soft, int(window * frac)))


def compute_dynamic_fan_in(
    *,
    doc_tokens: int,
    chunk_count: int,
    context_window: Optional[int] = None,
) -> Tuple[int, int]:
    """
    Continuous fan_in / max_depth from tokens, chunk count, and context window.
    Target: keep every compile prompt under the 80% context budget.
    """
    budget = context_token_budget()
    window = int(context_window or getattr(settings, "COMPILE_CONTEXT_WINDOW_TOKENS", 12000) or 12000)
    n = max(1, int(chunk_count or 1))
    toks = max(1, int(doc_tokens or n * 800))
    avg_chunk = max(50, toks // n)

    # How many child summaries fit under budget (leave headroom for instructions).
    usable = max(400, int(budget * 0.85))
    fan = max(2, min(24, usable // max(80, avg_chunk // 4)))
    # Deeper trees for larger docs
    if n <= 8:
        depth = 2
    else:
        # levels ≈ log_fan(n) + regional
        depth = int(math.ceil(math.log(max(2, n), max(2, fan)))) + 2
        depth = max(3, min(16, depth))
    # Prefer slightly wider fan when context is large
    if window >= 16000:
        fan = min(24, fan + 2)
    return int(fan), int(depth)


def _link_parents_children(nodes: Dict[str, DagNode]) -> None:
    for n in nodes.values():
        n.parent_ids = list(n.dep_ids)
        n.children_ids = []
    for n in nodes.values():
        for d in n.dep_ids:
            if d in nodes and n.id not in nodes[d].children_ids:
                nodes[d].children_ids.append(n.id)


def build_chunk_nodes(
    chunks: Sequence[Any],
    *,
    routes: Optional[Dict[int, Dict[str, Any]]] = None,
) -> Dict[str, DagNode]:
    """Create pending map-stage chunk nodes (not stub-completed)."""
    nodes: Dict[str, DagNode] = {}
    routes = routes or {}
    for i, chunk in enumerate(chunks):
        content = getattr(chunk, "content", None)
        if content is None and isinstance(chunk, dict):
            content = chunk.get("content")
        text = str(content or "")
        path = getattr(chunk, "section_path", None) or (
            chunk.get("section_path") if isinstance(chunk, dict) else None
        )
        route = routes.get(i) or {}
        nid = f"chunk-{i}"
        nodes[nid] = DagNode(
            id=nid,
            kind="chunk",
            depth=0,
            dep_ids=[],
            parent_ids=[],
            children_ids=[],
            status="pending",
            input_text=text,
            section_path=str(path or f"chunk-{i}"),
            token_estimate=estimate_tokens(text),
            tier=str(route.get("tier") or "medium"),
            chunk_index=i,
        )
    return nodes


def build_hierarchy_onto_chunks(
    nodes: Dict[str, DagNode],
    chunks: Sequence[Any],
    summaries: Sequence[str],
    *,
    fan_in: int,
    max_depth: int,
    skip_regional_below: int = 0,
    capability_score: float = 0.5,
    adaptive_regional: bool = True,
) -> Dict[str, DagNode]:
    """
    Attach regional/chapter/executive nodes above completed (or pending) chunk nodes.
    Chunk nodes keep their identity; hierarchy deps point at chunk-* ids.
    """
    # Ensure chunk nodes reflect current summaries when available
    for i, s in enumerate(summaries):
        nid = f"chunk-{i}"
        if nid in nodes and str(s or "").strip():
            if nodes[nid].status == "completed" or not nodes[nid].output_summary:
                nodes[nid].output_summary = str(s)
            # For hierarchy build, expose summary as text
    levels = hierarchy_mod.build_hierarchy_levels(
        chunks,
        summaries,
        fan_in=fan_in,
        max_depth=max_depth,
        skip_regional_below=skip_regional_below,
        capability_score=capability_score,
        adaptive_regional=adaptive_regional,
    )
    # Side-channel diagnostics (never insert meta nodes into the DAG).
    try:
        build_hierarchy_onto_chunks.last_compression_diag = (  # type: ignore[attr-defined]
            hierarchy_mod.hierarchy_diagnostics(levels)
        )
    except Exception:
        build_hierarchy_onto_chunks.last_compression_diag = {}  # type: ignore[attr-defined]
    level_ids: List[List[str]] = []
    for lv in levels:
        level_num = int(lv.get("level") or 0)
        kind = str(lv.get("kind") or "compile")
        ids_this: List[str] = []
        for n in list(lv.get("nodes") or []):
            nid = str(n.get("id"))
            if level_num == 0:
                # Already have chunk nodes
                if nid not in nodes:
                    nodes[nid] = DagNode(
                        id=nid,
                        kind="chunk",
                        depth=0,
                        status="pending",
                        input_text=str(n.get("text") or ""),
                        output_summary=str(n.get("text") or ""),
                        section_path=str(n.get("section_path") or ""),
                        token_estimate=int(n.get("token_estimate") or 0),
                        chunk_index=(n.get("source_indices") or [None])[0],
                    )
                ids_this.append(nid)
                continue
            k = kind
            if k == "compile":
                k = "executive" if level_num >= 3 else "chapter"
            if nid not in nodes:
                nodes[nid] = DagNode(
                    id=nid,
                    kind=k,
                    depth=level_num,
                    status="pending",
                    input_text=str(n.get("text") or ""),
                    section_path=str(n.get("section_path") or ""),
                    token_estimate=int(n.get("token_estimate") or 0),
                )
            ids_this.append(nid)
        level_ids.append(ids_this)

    pack_fan = max(2, int(fan_in or 8))
    for li, lv in enumerate(levels):
        if li == 0:
            continue
        kind = str(lv.get("kind") or "")
        cur = level_ids[li]
        prev = level_ids[li - 1]
        raw_nodes = list(lv.get("nodes") or [])
        for ci, cid in enumerate(cur):
            if kind == "regional" or (li == 1 and kind != "chapter"):
                src = [int(x) for x in (raw_nodes[ci].get("source_indices") or [])]
                deps = [f"chunk-{i}" for i in src if f"chunk-{i}" in nodes]
            else:
                start = ci * pack_fan
                end = min(len(prev), start + pack_fan)
                deps = prev[start:end]
            if not deps and prev:
                deps = [prev[min(ci, len(prev) - 1)]]
            nodes[cid].dep_ids = list(deps)
            nodes[cid].depth = li

    if level_ids:
        top = level_ids[-1]
        if len(top) > 1:
            fid = "final-executive"
            nodes[fid] = DagNode(
                id=fid,
                kind="executive",
                depth=len(level_ids),
                dep_ids=list(top),
                status="pending",
                section_path="executive",
            )
        elif len(top) == 1 and nodes[top[0]].kind != "chunk":
            nodes[top[0]].kind = "executive"

    _link_parents_children(nodes)
    return nodes


def insert_overflow_layer(
    nodes: Dict[str, DagNode],
    parent: DagNode,
    *,
    fan_in: Optional[int] = None,
) -> List[str]:
    """
    When a compile node's deps exceed the 80% budget, insert an intermediate
    fan-in layer instead of splitting text inside one prompt.
    Returns new intermediate node ids (already linked).
    """
    budget = context_token_budget()
    deps = [nodes[d] for d in parent.dep_ids if d in nodes]
    if not deps:
        return []

    def _dep_tokens(d: DagNode) -> int:
        if (d.output_summary or "").strip():
            return max(1, estimate_tokens(d.output_summary))
        return max(1, d.token_estimate or estimate_tokens(d.input_text or ""))

    total_tok = sum(_dep_tokens(d) for d in deps)
    if total_tok <= budget and estimate_tokens(parent.input_text or "") <= budget:
        return []

    # Dynamic sub-fan from child sizes
    avg = max(50, total_tok // max(1, len(deps)))
    sub_fan = fan_in or max(2, min(len(deps), budget // max(80, avg)))
    sub_fan = max(2, int(sub_fan))

    new_ids: List[str] = []
    batches = [deps[i : i + sub_fan] for i in range(0, len(deps), sub_fan)]
    if len(batches) <= 1:
        # Still too big — pack by token budget
        batches = []
        cur: List[DagNode] = []
        cur_tok = 0
        for d in deps:
            dt = _dep_tokens(d)
            if cur and cur_tok + dt > budget:
                batches.append(cur)
                cur, cur_tok = [], 0
            cur.append(d)
            cur_tok += dt
        if cur:
            batches.append(cur)

    if len(batches) <= 1:
        return []  # cannot further decompose; caller must stitch

    base_depth = parent.depth
    # Shift parent deeper
    parent.depth = base_depth + 1
    new_deps: List[str] = []
    for bi, batch in enumerate(batches):
        nid = _next_overflow_id(parent.id, bi)
        # Never overwrite an existing node id (guards against legacy collisions).
        while nid in nodes:
            nid = _next_overflow_id(parent.id, bi)
        parts = [b.output_summary or b.input_text for b in batch]
        text = "\n\n".join(parts)
        node = DagNode(
            id=nid,
            kind="chapter" if parent.kind == "executive" else "regional",
            depth=base_depth,
            dep_ids=[b.id for b in batch],
            status="pending",
            input_text=text,
            section_path=f"overflow/{parent.id}/{bi}",
            token_estimate=estimate_tokens(text),
        )
        nodes[nid] = node
        new_ids.append(nid)
        new_deps.append(nid)
        for b in batch:
            if parent.id in b.children_ids:
                b.children_ids = [c for c in b.children_ids if c != parent.id]
            if nid not in b.children_ids:
                b.children_ids.append(nid)

    parent.dep_ids = list(new_deps)
    # Parent will compile from child summaries after overflow children run —
    # do not re-join child input_text into the parent (that caused infinite re-insert).
    parent.input_text = ""
    parent.token_estimate = _expected_summary_token_cap(len(new_deps)) * len(new_deps)
    _link_parents_children(nodes)
    log.info(
        "Inserted overflow layer under %s: %s intermediate nodes (fan≈%s)",
        parent.id,
        len(new_ids),
        sub_fan,
    )
    try:
        from src.perf.critical_path import dag_audit_record_overflow, dag_audit_active_job

        job_id = dag_audit_active_job() or "_anon"
        regional_total = sum(1 for x in nodes.values() if x.kind == "regional")
        dag_audit_record_overflow(
            job_id,
            parent.id,
            new_ids,
            kind=str(parent.kind),
            nodes_total=len(nodes),
            regional_total=regional_total,
        )
    except Exception:
        pass
    return new_ids


def ensure_prompt_budget(nodes: Dict[str, DagNode], node_id: str) -> List[str]:
    """
    Recursively insert hierarchy levels until node input fits budget.
    Returns all newly inserted node ids (including nested).

    PRODUCTION HARDENING: when unified frozen-DAG execution is enabled, topology
    mutation is allowed ONLY during planning (``allow_planning_overflow(True)``).
    Calls during execution raise immediately.
    """
    n = nodes.get(node_id)
    if not n or n.kind == "chunk":
        return []
    est, parts = estimate_compile_prompt_tokens(nodes, n)
    if parts:
        n.input_text = parts
    n.token_estimate = est
    budget = context_token_budget()
    if n.token_estimate <= budget:
        return []

    # Over budget — may need overflow inserts
    unified = bool(getattr(settings, "UNIFIED_DAG_EXECUTOR_ENABLED", True))
    if unified and not _PLANNING_OVERFLOW_ALLOWED:
        raise RuntimeError(
            f"ensure_prompt_budget({node_id}) refused after planning: "
            f"frozen DAG forbids topology mutation "
            f"(token_estimate={n.token_estimate} budget={budget})"
        )

    all_inserted: List[str] = []
    guard = 0
    while n.token_estimate > budget and guard < 6:
        inserted = insert_overflow_layer(nodes, n)
        if not inserted:
            break
        all_inserted.extend(inserted)
        # Newly inserted nodes may themselves overflow
        for iid in inserted:
            all_inserted.extend(ensure_prompt_budget(nodes, iid))
        # Re-estimate from summary-sized child contributions, not full child inputs
        est, parts = estimate_compile_prompt_tokens(nodes, n)
        n.token_estimate = est
        if parts:
            n.input_text = parts
        else:
            n.input_text = ""
        guard += 1
    return all_inserted


def dag_progress_snapshot(nodes: Dict[str, DagNode], *, workers_busy: int = 0, workers_total: int = 0) -> Dict[str, Any]:
    by_kind: Dict[str, Dict[str, int]] = {}
    # Separate overflow inserts (*-ovf-*) from original hierarchy for audit UI.
    overflow_by_kind: Dict[str, Dict[str, int]] = {}
    baseline_by_kind: Dict[str, Dict[str, int]] = {}
    done = run = fail = pending = retrying = 0
    carbon = 0.0
    lat_sum = 0.0
    lat_n = 0

    def _bump(bucket_map: Dict[str, Dict[str, int]], kind: str, st: str) -> None:
        bucket = bucket_map.setdefault(
            kind, {"done": 0, "total": 0, "running": 0, "failed": 0, "pending": 0, "retrying": 0}
        )
        bucket["total"] += 1
        if st == "completed":
            bucket["done"] += 1
        elif st == "running":
            bucket["running"] += 1
        elif st == "failed":
            bucket["failed"] += 1
        elif st == "retrying":
            bucket["retrying"] += 1
        else:
            bucket["pending"] += 1

    for n in nodes.values():
        bucket = by_kind.setdefault(
            n.kind, {"done": 0, "total": 0, "running": 0, "failed": 0, "pending": 0, "retrying": 0}
        )
        bucket["total"] += 1
        st = n.status
        is_ovf = "-ovf-" in str(n.id) or str(n.section_path or "").startswith("overflow/")
        _bump(overflow_by_kind if is_ovf else baseline_by_kind, n.kind, st)
        if st == "completed":
            bucket["done"] += 1
            done += 1
            carbon += float(n.carbon_estimate_g or 0.0)
            if n.latency_ms:
                lat_sum += n.latency_ms
                lat_n += 1
        elif st == "running":
            bucket["running"] += 1
            run += 1
        elif st == "failed":
            bucket["failed"] += 1
            fail += 1
        elif st == "retrying":
            bucket["retrying"] += 1
            retrying += 1
        else:
            bucket["pending"] += 1
            pending += 1
    total = max(1, done + run + fail + pending + retrying)
    remaining = pending + run + retrying
    avg_lat = (lat_sum / lat_n) if lat_n else 0.0
    return {
        "by_kind": by_kind,
        "baseline": baseline_by_kind,
        "overflow": overflow_by_kind,
        "completed": done,
        "running": run,
        "failed": fail,
        "pending": pending,
        "retrying": retrying,
        "remaining": remaining,
        "total": total,
        "workers_busy": workers_busy,
        "workers_total": workers_total,
        "avg_latency_ms": round(avg_lat, 1),
        "carbon_g": round(carbon, 4),
        "chunks": by_kind.get("chunk", {}),
        "regional": by_kind.get("regional", {}),
        "chapter": by_kind.get("chapter", {}),
        "executive": by_kind.get("executive", {}),
        # Audit fields: original vs dynamically inserted
        "regional_baseline": (baseline_by_kind.get("regional") or {}).get("total", 0),
        "regional_overflow": (overflow_by_kind.get("regional") or {}).get("total", 0),
        "chapter_overflow": (overflow_by_kind.get("chapter") or {}).get("total", 0),
    }


def carbon_rollups(nodes: Dict[str, DagNode]) -> Dict[str, Any]:
    by_level: Dict[str, float] = {}
    by_worker: Dict[str, float] = {}
    by_model: Dict[str, float] = {}
    by_kind: Dict[str, float] = {}
    energy = 0.0
    cost = 0.0
    tokens = 0
    for n in nodes.values():
        c = float(n.carbon_estimate_g or 0.0)
        by_level[str(n.depth)] = by_level.get(str(n.depth), 0.0) + c
        by_kind[n.kind] = by_kind.get(n.kind, 0.0) + c
        if n.worker_id:
            by_worker[str(n.worker_id)] = by_worker.get(str(n.worker_id), 0.0) + c
        if n.assigned_model:
            by_model[str(n.assigned_model)] = by_model.get(str(n.assigned_model), 0.0) + c
        energy += float(n.energy_kwh or 0.0)
        cost += float(n.cost_usd or 0.0)
        tokens += int(n.tokens_in or 0) + int(n.tokens_out or 0)
    return {
        "by_hierarchy_level": {k: round(v, 4) for k, v in by_level.items()},
        "by_worker": {k: round(v, 4) for k, v in by_worker.items()},
        "by_model": {k: round(v, 4) for k, v in by_model.items()},
        "by_kind": {k: round(v, 4) for k, v in by_kind.items()},
        "total_carbon_g": round(sum(by_kind.values()), 4),
        "total_energy_kwh": round(energy, 8),
        "total_cost_usd": round(cost, 6),
        "total_tokens": tokens,
    }


def critical_path_ms(nodes: Dict[str, DagNode]) -> float:
    """
    Longest dependency chain by actual elapsed latency.

    Iterative Kahn-style DP — safe for deep trees and dependency cycles
    (cycles are broken; cyclic nodes keep their own latency only).
    """
    if not nodes:
        return 0.0
    from collections import deque

    indeg: Dict[str, int] = {nid: 0 for nid in nodes}
    children: Dict[str, List[str]] = {nid: [] for nid in nodes}
    for nid, n in nodes.items():
        for d in n.dep_ids:
            if d not in nodes or d == nid:
                continue
            children[d].append(nid)
            indeg[nid] += 1

    dist = {nid: float(nodes[nid].latency_ms or 0.0) for nid in nodes}
    q = deque([nid for nid, deg in indeg.items() if deg == 0])
    while q:
        u = q.popleft()
        base = dist[u]
        for v in children[u]:
            cand = float(nodes[v].latency_ms or 0.0) + base
            if cand > dist[v]:
                dist[v] = cand
            indeg[v] -= 1
            if indeg[v] == 0:
                q.append(v)
    return max(dist.values(), default=0.0)


def perf_metrics(
    nodes: Dict[str, DagNode],
    *,
    wall_ms: float,
    workers: int,
    queue_wait_ms_avg: float = 0.0,
    api_calls: int = 0,
    sequential_baseline_ms: Optional[float] = None,
    cpu_pct: Optional[float] = None,
    memory_mb: Optional[float] = None,
) -> Dict[str, Any]:
    snap = dag_progress_snapshot(nodes, workers_total=workers)
    try:
        cp = critical_path_ms(nodes)
    except Exception as e:
        log.warning("critical_path_ms failed (non-fatal): %s", e)
        cp = 0.0
    # Identify critical node (max single-node latency on the longest path heuristic)
    critical_node = None
    critical_stage = None
    critical_latency = 0.0
    for n in nodes.values():
        ms = float(n.latency_ms or 0.0)
        if ms > critical_latency:
            critical_latency = ms
            critical_node = n.id
            critical_stage = n.kind
    sum_lat = sum(float(n.latency_ms or 0.0) for n in nodes.values())
    seq = float(sequential_baseline_ms) if sequential_baseline_ms else max(sum_lat, cp)
    speedup = (seq / wall_ms) if wall_ms > 0 else 0.0
    # Parallel efficiency ≈ speedup / workers
    efficiency = (speedup / workers) if workers else 0.0
    util = 0.0
    if wall_ms > 0 and workers > 0:
        util = min(1.0, sum_lat / (wall_ms * workers))
    roll = carbon_rollups(nodes)
    return {
        "worker_utilization": round(util, 4),
        "queue_wait_ms_avg": round(queue_wait_ms_avg, 1),
        "execution_time_ms": round(wall_ms, 1),
        "critical_path_ms": round(cp, 1),
        "critical_node": critical_node,
        "critical_stage": critical_stage,
        "critical_latency_ms": round(critical_latency, 1),
        "parallel_efficiency": round(efficiency, 4),
        "speedup_vs_sequential": round(speedup, 3),
        "sequential_baseline_ms": round(seq, 1),
        "cpu_pct": cpu_pct,
        "memory_mb": memory_mb,
        "api_calls": api_calls,
        "carbon_g": roll["total_carbon_g"],
        "workers": workers,
        "nodes_completed": snap["completed"],
        "nodes_total": snap["total"],
    }
