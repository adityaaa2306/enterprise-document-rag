#!/usr/bin/env python3
"""Diagnose recent jobs: hierarchy shape, overflow, carbon, timings."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _loads(x):
    if x is None:
        return None
    if isinstance(x, (dict, list)):
        return x
    try:
        return json.loads(x)
    except Exception:
        return None


def summarize_result(job_id: str, result: dict | None, meta: dict) -> dict:
    result = result or {}
    cd = result.get("carbon_data") or {}
    cm = result.get("compile_meta") or {}
    plan = result.get("execution_plan") or {}
    dag = cm.get("dag_nodes") or result.get("pipeline_dag_nodes") or {}
    rollups = cm.get("carbon_rollups") or result.get("carbon_rollups") or {}
    perf = cm.get("perf_metrics") or result.get("perf_metrics") or {}
    hier = result.get("hierarchy") or cm.get("hierarchy") or {}

    by_kind = {}
    overflow = []
    started = []
    for nid, n in (dag.items() if isinstance(dag, dict) else []):
        if not isinstance(n, dict):
            continue
        k = n.get("kind") or "?"
        by_kind[k] = by_kind.get(k, 0) + 1
        if "-ovf-" in str(nid) or str(n.get("section_path") or "").startswith("overflow/"):
            overflow.append(
                {
                    "id": nid,
                    "kind": k,
                    "deps": n.get("dep_ids"),
                    "status": n.get("status"),
                    "latency_ms": n.get("latency_ms"),
                    "carbon": n.get("carbon_estimate_g"),
                }
            )
        if n.get("started_at") is not None and n.get("finished_at") is not None:
            started.append(
                {
                    "id": nid,
                    "kind": k,
                    "started_at": n.get("started_at"),
                    "finished_at": n.get("finished_at"),
                    "latency_ms": n.get("latency_ms"),
                    "queue_wait_ms": n.get("queue_wait_ms"),
                    "retries": n.get("retries"),
                    "model": n.get("assigned_model"),
                    "carbon": n.get("carbon_estimate_g"),
                    "tokens_in": n.get("tokens_in"),
                    "tokens_out": n.get("tokens_out"),
                }
            )

    # Layer idle gaps (monotonic timestamps)
    gaps = {}
    by_k_times = {}
    for row in started:
        by_k_times.setdefault(row["kind"], []).append(row)
    for k, rows in by_k_times.items():
        rows.sort(key=lambda r: float(r["started_at"]))
    order = ["chunk", "regional", "chapter", "executive", "final"]
    for a, b in zip(order, order[1:]):
        ra, rb = by_k_times.get(a) or [], by_k_times.get(b) or []
        if not ra or not rb:
            gaps[f"{a}->{b}"] = None
            continue
        a_end = max(float(r["finished_at"]) for r in ra)
        b_start = min(float(r["started_at"]) for r in rb)
        gaps[f"{a}->{b}"] = round(b_start - a_end, 3)

    carbon_actual = (
        cd.get("actual_cost_gco2e")
        or cd.get("estimated_optimized_pipeline_emissions_g")
        or result.get("carbon_spent_g")
        or rollups.get("total_carbon_g")
    )
    return {
        **meta,
        "job_id": job_id,
        "filename": result.get("filename") or meta.get("filename"),
        "carbon_dashboard": carbon_actual,
        "carbon_saved_grams_col": meta.get("carbon_saved_grams"),
        "carbon_data_keys": sorted(cd.keys()) if cd else [],
        "carbon_data_subset": {
            k: cd.get(k)
            for k in (
                "actual_cost_gco2e",
                "baseline_cost_gco2e",
                "estimated_optimized_pipeline_emissions_g",
                "estimated_baseline_pipeline_emissions_g",
                "carbon_saved_grams",
                "chunk_breakdown",
                "methodology",
            )
            if k in cd
        },
        "rollups": rollups,
        "perf": perf,
        "plan": {
            "by_kind": plan.get("by_kind"),
            "node_count": plan.get("node_count"),
            "regional": plan.get("regional"),
            "chapter": plan.get("chapter"),
            "executive": plan.get("executive"),
            "overflow_ids": plan.get("overflow_ids"),
            "overflow_n": len(plan.get("overflow_ids") or []),
            "fingerprint": plan.get("fingerprint"),
            "max_depth": plan.get("max_depth"),
            "hierarchy_fan_in": plan.get("hierarchy_fan_in"),
        },
        "hierarchy_ui_levels": [
            {
                "level": lv.get("level"),
                "kind": lv.get("kind"),
                "node_count": lv.get("node_count"),
            }
            for lv in (hier.get("levels") or [])
        ],
        "dag_by_kind": by_kind,
        "overflow_nodes": overflow,
        "layer_idle_gaps_sec": gaps,
        "node_timing_sample": sorted(started, key=lambda r: float(r["started_at"]))[:5]
        + sorted(started, key=lambda r: float(r["started_at"]))[-5:],
        "compile_engine": cm.get("engine"),
        "escalation_count": result.get("escalation_count") or cm.get("escalation_count"),
        "stage_timings": result.get("stage_timings_ms")
        or (result.get("ingestion_latency") or {}).get("stages_ms"),
        "summary_ready": result.get("summary_ready"),
        "background": result.get("background"),
    }


def main() -> None:
    from sqlalchemy import text
    from src.db.session import get_session_factory

    s = get_session_factory()()
    rows = s.execute(
        text(
            """
            SELECT id, status, progress, message, filename, job_mode,
                   carbon_saved_grams, result_json, created_at, updated_at,
                   completed_at, latency_ms
            FROM jobs
            ORDER BY updated_at DESC NULLS LAST
            LIMIT 25
            """
        )
    ).mappings().all()

    reports = []
    for r in rows:
        d = dict(r)
        result = _loads(d.pop("result_json", None))
        meta = {
            "status": d.get("status"),
            "progress": d.get("progress"),
            "message": (d.get("message") or "")[:160],
            "filename": d.get("filename"),
            "job_mode": d.get("job_mode"),
            "carbon_saved_grams": d.get("carbon_saved_grams"),
            "updated_at": str(d.get("updated_at")),
            "latency_ms": d.get("latency_ms"),
        }
        rep = summarize_result(str(d.get("id")), result, meta)
        reports.append(rep)
        print(
            json.dumps(
                {
                    "id": rep["job_id"],
                    "file": rep.get("filename"),
                    "status": rep.get("status"),
                    "carbon": rep.get("carbon_dashboard"),
                    "plan": rep.get("plan"),
                    "dag_by_kind": rep.get("dag_by_kind"),
                    "overflow_n": len(rep.get("overflow_nodes") or []),
                    "gaps": rep.get("layer_idle_gaps_sec"),
                    "updated": rep.get("updated_at"),
                },
                default=str,
            )
        )

    # Prefer job with ~30 regional or ~41g carbon
    target = None
    for rep in reports:
        c = rep.get("carbon_dashboard")
        regional = (rep.get("dag_by_kind") or {}).get("regional") or (rep.get("plan") or {}).get(
            "regional"
        )
        if c is not None and 35 <= float(c) <= 50:
            target = rep
            break
        if regional and int(regional) >= 25:
            target = rep
            break
    if target is None and reports:
        target = reports[0]

    out = {"recent": reports, "focus": target}
    Path("eval_out/_inefficiency_diag.json").write_text(
        json.dumps(out, indent=2, default=str), encoding="utf-8"
    )
    print("\nFOCUS", target.get("job_id") if target else None)
    if target:
        print(json.dumps(target, indent=2, default=str)[:8000])
    s.close()


if __name__ == "__main__":
    main()
