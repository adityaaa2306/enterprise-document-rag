"""
Production execution inspector — replayable per-job trace.

Primary debugging artifact for planning → frozen DAG → execution → Summary Ready → background.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


def _default_dir() -> Path:
    base = Path(__file__).resolve().parents[2] / "eval_out" / "execution_traces"
    base.mkdir(parents=True, exist_ok=True)
    return base


def write_execution_trace(
    job_id: str,
    *,
    plan: Any,
    nodes: Dict[str, Any],
    dag_out: Dict[str, Any],
    stage_timings_ms: Dict[str, float],
    rollups: Dict[str, Any],
    metrics: Dict[str, Any],
    fingerprint_before: str,
    fingerprint_after: Optional[str] = None,
    out_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Build and persist a replayable execution inspector payload."""
    plan_d = plan.to_dict() if hasattr(plan, "to_dict") else dict(plan or {})
    node_timeline: List[Dict[str, Any]] = []
    for nid, n in nodes.items():
        d = n.to_dict() if hasattr(n, "to_dict") else dict(n)
        node_timeline.append(
            {
                "id": nid,
                "kind": d.get("kind"),
                "status": d.get("status"),
                "depth": d.get("depth"),
                "dep_ids": d.get("dep_ids"),
                "latency_ms": d.get("latency_ms"),
                "carbon_estimate_g": d.get("carbon_estimate_g"),
                "assigned_model": d.get("assigned_model"),
                "tokens_in": d.get("tokens_in"),
                "tokens_out": d.get("tokens_out"),
                "attempts": d.get("attempts"),
                "started_at": d.get("started_at"),
                "finished_at": d.get("finished_at"),
                "error": d.get("error"),
            }
        )

    # Critical path from perf metrics / node latencies
    critical = {
        "critical_path_ms": (metrics or {}).get("critical_path_ms"),
        "critical_node": (metrics or {}).get("critical_node"),
        "critical_stage": (metrics or {}).get("critical_stage"),
        "critical_latency_ms": (metrics or {}).get("critical_latency_ms"),
        "waits_gt_2s": (dag_out.get("dag_audit") or {}).get("waits_gt_2s") or [],
    }
    if not critical.get("critical_node"):
        # Derive from max latency among completed compile nodes
        best = None
        best_ms = -1.0
        for row in node_timeline:
            if row.get("kind") == "chunk":
                continue
            ms = float(row.get("latency_ms") or 0)
            if ms > best_ms:
                best_ms = ms
                best = row
        if best:
            critical["critical_node"] = best["id"]
            critical["critical_stage"] = best.get("kind")
            critical["critical_latency_ms"] = best_ms

    operational_g = float(
        (rollups or {}).get("total_carbon_g")
        or (rollups or {}).get("total_g")
        or 0.0
    )
    if not operational_g:
        operational_g = sum(float(r.get("carbon_estimate_g") or 0) for r in node_timeline)

    trace: Dict[str, Any] = {
        "schema": "execution_inspector_v1",
        "job_id": job_id,
        "generated_at": time.time(),
        "planning": {
            "fingerprint": plan_d.get("fingerprint"),
            "node_count": plan_d.get("node_count"),
            "by_kind": plan_d.get("by_kind"),
            "overflow_ids": plan_d.get("overflow_ids"),
            "expected_runtime_sec": plan_d.get("expected_runtime_sec"),
            "expected_carbon_g": plan_d.get("expected_carbon_g"),
            "expected_api_calls": plan_d.get("expected_api_calls"),
            "expected_cost_usd": plan_d.get("expected_cost_usd"),
            "compression": plan_d.get("compression"),
            "estimate_basis": plan_d.get("estimate_basis"),
        },
        "frozen_dag": {
            "fingerprint_before": fingerprint_before,
            "fingerprint_after": fingerprint_after or dag_out.get("fingerprint_after"),
            "immutable": fingerprint_before
            == (fingerprint_after or dag_out.get("fingerprint_after") or fingerprint_before),
            "node_ids": plan_d.get("node_ids"),
            "topology_edge_count": sum(
                len((t or {}).get("dep_ids") or [])
                for t in (plan_d.get("topology") or {}).values()
            ),
        },
        "hierarchy": dag_out.get("hierarchy") or {},
        "worker_allocation": {
            "compile_workers": plan_d.get("compile_workers"),
            "map_workers": plan_d.get("map_workers"),
            "perf_metrics": metrics,
        },
        "endpoint_allocation": dag_out.get("endpoint_pool") or {},
        "execution_timeline": node_timeline,
        "critical_path": critical,
        "carbon": {
            "operational_co2e_g": operational_g,
            "label_primary": "Operational CO₂e",
            "rollups": rollups,
            "compile_carbon_g": dag_out.get("compile_carbon_g"),
        },
        "cost": {
            "expected_usd": plan_d.get("expected_cost_usd"),
            "node_cost_usd_sum": sum(float(getattr(n, "cost_usd", 0) or 0) for n in nodes.values()),
        },
        "latency": {
            "stage_timings_ms": stage_timings_ms,
            "wall_ms": (metrics or {}).get("execution_time_ms"),
        },
        "retries": {
            "branch_recompiles": dag_out.get("branch_recompiles") or [],
            "repair_report": dag_out.get("repair_report") or {},
        },
        "failures": [
            r for r in node_timeline if r.get("status") == "failed" or r.get("error")
        ],
        "dag_audit": dag_out.get("dag_audit") or {},
        "background_timeline": {
            "note": "Filled by background_services after Summary Ready",
            "phases": ["queued", "indexing", "embeddings", "carbon", "search_ready"],
        },
    }

    directory = out_dir or _default_dir()
    path = directory / f"{job_id}.json"
    try:
        path.write_text(json.dumps(trace, indent=2, default=str), encoding="utf-8")
        log.info("Job %s: execution inspector written → %s", job_id, path)
    except Exception as e:
        log.warning("Job %s: could not write execution inspector: %s", job_id, e)
    # Also attach path for API/debug
    trace["_path"] = str(path)
    return trace


def load_execution_trace(job_id: str, *, out_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    path = (out_dir or _default_dir()) / f"{job_id}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
