"""
Planning phase — deterministic DAG construction before any compile LLM call.

Freeze contract:
  - Hierarchy + overflow inserts happen ONLY here.
  - After ``freeze_dag()``, topology (ids, dep_ids, kinds) is immutable.
  - Execution may only update status / output_summary / telemetry fields.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from src.core import pipeline_dag as pdag
from src.core.config import settings

log = logging.getLogger(__name__)

# Fields that execution MAY mutate on a frozen node
_MUTABLE_FIELDS = frozenset(
    {
        "status",
        "output_summary",
        "latency_ms",
        "carbon_estimate_g",
        "assigned_model",
        "started_at",
        "finished_at",
        "attempts",
        "used_heavy",
        "cancel_requested",
        "confidence",
        "tokens_in",
        "tokens_out",
        "cost_usd",
        "energy_kwh",
        "error",
        "input_text",  # may refresh from completed deps (content only)
        "token_estimate",
    }
)

# Historical EMA for planner convergence (process-local)
_EMA_LOCK = threading.Lock()
_PLANNER_EMA: Dict[str, float] = {
    "runtime_sec": 60.0,
    "carbon_g": 1.0,
    "cost_usd": 0.01,
    "api_calls": 20.0,
    "hierarchy_depth": 3.0,
    "sec_per_compile_node": 8.0,
    "carbon_per_compile_node": 0.02,
}
_EMA_ALPHA = 0.25


@dataclass
class ExecutionPlan:
    job_id: str
    frozen: bool = False
    fingerprint: str = ""
    node_ids: List[str] = field(default_factory=list)
    node_count: int = 0
    by_kind: Dict[str, int] = field(default_factory=dict)
    overflow_ids: List[str] = field(default_factory=list)
    regional: int = 0
    chapter: int = 0
    executive: int = 0
    chunk: int = 0
    max_depth: int = 0
    max_parallelism: int = 0
    compile_workers: int = 0
    map_workers: int = 0
    expected_api_calls: int = 0
    expected_runtime_sec: float = 0.0
    expected_carbon_g: float = 0.0
    expected_cost_usd: float = 0.0
    expected_hierarchy_depth: int = 0
    hierarchy_fan_in: int = 8
    qva_tau: float = 0.58
    compile_tau: float = 0.58
    medium_first: bool = True
    planned_at: float = 0.0
    topology: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    compression: Dict[str, Any] = field(default_factory=dict)
    capability_score: float = 0.5
    estimate_basis: str = "ema+topology"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _topology_snapshot(nodes: Dict[str, pdag.DagNode]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for nid, n in nodes.items():
        out[nid] = {
            "id": n.id,
            "kind": n.kind,
            "depth": n.depth,
            "dep_ids": list(n.dep_ids or []),
            "children_ids": list(n.children_ids or []),
            "section_path": str(n.section_path or ""),
        }
    return out


def fingerprint_topology(nodes: Dict[str, pdag.DagNode]) -> str:
    topo = _topology_snapshot(nodes)
    payload = json.dumps(topo, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def assert_dag_immutable(
    nodes: Dict[str, pdag.DagNode],
    plan: ExecutionPlan,
    *,
    phase: str = "execution",
) -> None:
    """Raise if topology drifted from the frozen plan."""
    if not plan.frozen:
        return
    current_ids = set(nodes.keys())
    planned_ids = set(plan.node_ids)
    if current_ids != planned_ids:
        added = sorted(current_ids - planned_ids)
        removed = sorted(planned_ids - current_ids)
        raise RuntimeError(
            f"DAG mutated during {phase}: added={added[:10]} removed={removed[:10]}"
        )
    fp = fingerprint_topology(nodes)
    if plan.fingerprint and fp != plan.fingerprint:
        raise RuntimeError(
            f"DAG fingerprint drift during {phase}: planned={plan.fingerprint} now={fp}"
        )
    for nid, expected in plan.topology.items():
        n = nodes.get(nid)
        if n is None:
            raise RuntimeError(f"DAG mutated during {phase}: missing node {nid}")
        if list(n.dep_ids or []) != list(expected.get("dep_ids") or []):
            raise RuntimeError(
                f"DAG dep rewrite during {phase}: {nid} "
                f"{expected.get('dep_ids')} → {n.dep_ids}"
            )
        if n.kind != expected.get("kind"):
            raise RuntimeError(
                f"DAG kind rewrite during {phase}: {nid} "
                f"{expected.get('kind')} → {n.kind}"
            )


def planner_ema_snapshot() -> Dict[str, float]:
    with _EMA_LOCK:
        return dict(_PLANNER_EMA)


def update_planner_ema(actual: Dict[str, Any]) -> Dict[str, float]:
    """
    Converge planner estimates toward observed executions (exponential moving avg).
    """
    alpha = _EMA_ALPHA
    with _EMA_LOCK:
        mapping = {
            "runtime_sec": actual.get("runtime_sec"),
            "carbon_g": actual.get("carbon_g"),
            "cost_usd": actual.get("cost_usd"),
            "api_calls": actual.get("api_calls"),
            "hierarchy_depth": actual.get("hierarchy_depth"),
            "sec_per_compile_node": actual.get("sec_per_compile_node"),
            "carbon_per_compile_node": actual.get("carbon_per_compile_node"),
        }
        for k, v in mapping.items():
            if v is None:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if fv < 0:
                continue
            prev = float(_PLANNER_EMA.get(k) or fv)
            _PLANNER_EMA[k] = (1.0 - alpha) * prev + alpha * fv
        return dict(_PLANNER_EMA)


def _estimate_from_ema(
    compile_nodes: int,
    depth: int,
    workers: int,
    intensity: float,
) -> Dict[str, float]:
    ema = planner_ema_snapshot()
    sec_per = max(0.5, float(ema.get("sec_per_compile_node") or 8.0))
    waves = max(1, int((compile_nodes + max(1, workers) - 1) / max(1, workers)))
    runtime = waves * sec_per
    # Blend with historical wall-clock when available
    hist_rt = float(ema.get("runtime_sec") or runtime)
    hist_calls = max(1.0, float(ema.get("api_calls") or compile_nodes))
    runtime = 0.6 * runtime + 0.4 * hist_rt * (compile_nodes / hist_calls)
    carbon_per = float(ema.get("carbon_per_compile_node") or 0.02) * (intensity / 500.0)
    carbon = compile_nodes * carbon_per
    cost = float(ema.get("cost_usd") or 0.01) * (compile_nodes / hist_calls)
    return {
        "runtime_sec": round(max(1.0, runtime), 1),
        "carbon_g": round(max(0.0, carbon), 4),
        "cost_usd": round(max(0.0, cost), 5),
        "api_calls": float(compile_nodes),
        "hierarchy_depth": float(depth),
    }


def plan_compile_hierarchy(
    nodes: Dict[str, pdag.DagNode],
    chunks: Sequence[Any],
    summaries: Sequence[str],
    *,
    job_id: str,
    fan_in: int,
    max_depth: int,
    skip_regional_below: int = 0,
    map_workers: Optional[int] = None,
    compile_workers: Optional[int] = None,
    qva_tau: float = 0.58,
    compile_tau: float = 0.58,
    medium_first: bool = True,
    intensity: float = 500.0,
    capability_score: float = 0.5,
    adaptive_regional: bool = True,
) -> Tuple[Dict[str, pdag.DagNode], ExecutionPlan]:
    """
    Build hierarchy + predict overflow, then FREEZE.

    Must be called once after map/QVA and before any compile LLM call.
    """
    t0 = time.perf_counter()
    pdag.allow_planning_overflow(True)
    compression: Dict[str, Any] = {}
    overflow_ids: List[str] = []
    try:
        nodes = pdag.build_hierarchy_onto_chunks(
            nodes,
            chunks,
            summaries,
            fan_in=fan_in,
            max_depth=max_depth,
            skip_regional_below=skip_regional_below,
            capability_score=capability_score,
            adaptive_regional=adaptive_regional,
        )
        compression = dict(
            getattr(pdag.build_hierarchy_onto_chunks, "last_compression_diag", {}) or {}
        )
        # Predict overflow until stable (planning only)
        guard = 0
        while guard < 8:
            guard += 1
            inserted_any = False
            for nid, n in list(nodes.items()):
                if n.kind == "chunk" or n.status not in ("pending", "retrying", "completed"):
                    continue
                before = set(nodes.keys())
                new_ids = pdag.ensure_prompt_budget(nodes, nid)
                if new_ids:
                    overflow_ids.extend(new_ids)
                    inserted_any = True
                elif set(nodes.keys()) - before:
                    overflow_ids.extend(sorted(set(nodes.keys()) - before))
                    inserted_any = True
            if not inserted_any:
                break
    finally:
        # Ban further topology mutation for this process until next plan call
        pdag.allow_planning_overflow(False)

    # Deduplicate overflow ids
    seen: Set[str] = set()
    overflow_unique: List[str] = []
    for oid in overflow_ids:
        if oid not in seen and oid in nodes:
            seen.add(oid)
            overflow_unique.append(oid)

    by_kind: Dict[str, int] = {}
    for n in nodes.values():
        by_kind[n.kind] = by_kind.get(n.kind, 0) + 1

    mw = max(1, int(map_workers or settings.effective_parallel_workers()))
    cw = max(1, int(compile_workers or settings.effective_compile_max_workers()))
    compile_nodes = sum(1 for n in nodes.values() if n.kind != "chunk")
    depth = max((n.depth for n in nodes.values()), default=0)
    est = _estimate_from_ema(compile_nodes, depth, cw, intensity)

    fp = fingerprint_topology(nodes)
    plan = ExecutionPlan(
        job_id=job_id,
        frozen=True,
        fingerprint=fp,
        node_ids=sorted(nodes.keys()),
        node_count=len(nodes),
        by_kind=dict(by_kind),
        overflow_ids=overflow_unique,
        regional=int(by_kind.get("regional") or 0),
        chapter=int(by_kind.get("chapter") or 0),
        executive=int(by_kind.get("executive") or 0),
        chunk=int(by_kind.get("chunk") or 0),
        max_depth=depth,
        max_parallelism=cw,
        compile_workers=cw,
        map_workers=mw,
        expected_api_calls=int(est["api_calls"]),
        expected_runtime_sec=float(est["runtime_sec"]),
        expected_carbon_g=float(est["carbon_g"]),
        expected_cost_usd=float(est["cost_usd"]),
        expected_hierarchy_depth=int(depth),
        hierarchy_fan_in=fan_in,
        qva_tau=qva_tau,
        compile_tau=compile_tau,
        medium_first=medium_first,
        planned_at=time.time(),
        topology=_topology_snapshot(nodes),
        compression=compression,
        capability_score=float(capability_score),
        estimate_basis="ema+topology",
    )
    log.info(
        "Job %s: PLAN frozen fingerprint=%s nodes=%s regional=%s chapter=%s "
        "executive=%s overflow=%s depth=%s workers=%s compression=%s plan_ms=%.0f "
        "est_runtime=%.1fs est_carbon=%.4fg",
        job_id,
        fp,
        plan.node_count,
        plan.regional,
        plan.chapter,
        plan.executive,
        len(plan.overflow_ids),
        plan.max_depth,
        cw,
        compression.get("compression_ratio"),
        (time.perf_counter() - t0) * 1000.0,
        plan.expected_runtime_sec,
        plan.expected_carbon_g,
    )
    return nodes, plan


def format_execution_plan(plan: ExecutionPlan) -> str:
    lines = [
        "=== Execution Plan ===",
        f"job_id              = {plan.job_id}",
        f"fingerprint         = {plan.fingerprint}",
        f"node_count          = {plan.node_count}",
        f"chunks              = {plan.chunk}",
        f"regional            = {plan.regional}",
        f"chapter             = {plan.chapter}",
        f"executive           = {plan.executive}",
        f"overflow_predicted  = {len(plan.overflow_ids)}",
        f"max_depth           = {plan.max_depth}",
        f"max_parallelism     = {plan.max_parallelism}",
        f"compile_workers     = {plan.compile_workers}",
        f"expected_api_calls  = {plan.expected_api_calls}",
        f"expected_runtime_s  = {plan.expected_runtime_sec}",
        f"expected_carbon_g   = {plan.expected_carbon_g}",
        f"expected_cost_usd   = {plan.expected_cost_usd}",
        f"compression_ratio   = {(plan.compression or {}).get('compression_ratio')}",
        f"avg_chunks/regional = {(plan.compression or {}).get('avg_chunks_per_regional')}",
        f"estimate_basis      = {plan.estimate_basis}",
    ]
    return "\n".join(lines)
