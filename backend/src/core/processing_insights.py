"""
Build ProcessingInsights for job-result / UX (Smart Routing redesign).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def build_processing_insights(
    *,
    routing_decision: Optional[Dict[str, Any]] = None,
    cre_result: Optional[Dict[str, Any]] = None,
    carbon_report: Optional[Dict[str, Any]] = None,
    validation_verdict: Optional[Dict[str, Any]] = None,
    job_mode: Optional[str] = None,
    latency_ms: Optional[float] = None,
    routing_distribution: Optional[Dict[str, Any]] = None,
    chunk_routing: Optional[List[Dict[str, Any]]] = None,
    hierarchy: Optional[Dict[str, Any]] = None,
    agent_telemetry: Optional[List[Dict[str, Any]]] = None,
    compile_meta: Optional[Dict[str, Any]] = None,
    carbon_budget_g: Optional[float] = None,
    carbon_spent_g: Optional[float] = None,
    carbon_remaining_g: Optional[float] = None,
    predicted_final_carbon_g: Optional[float] = None,
    ingestion_latency: Optional[Dict[str, Any]] = None,
    triage_meta: Optional[Dict[str, Any]] = None,
    pipeline_intelligence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    decision = routing_decision or {}
    cre = cre_result or {}
    carbon = carbon_report or {}
    verdict = validation_verdict or {}
    side = carbon.get("routing") if isinstance(carbon.get("routing"), dict) else {}
    dist = routing_distribution or {}
    tmeta = triage_meta or {}
    intel = pipeline_intelligence or {}

    escalations: List[Any] = decision.get("escalations") or side.get("escalations") or []
    chunks_escalated = int(carbon.get("chunks_escalated") or 0)
    escalation_required = bool(escalations) or chunks_escalated > 0

    crs = decision.get("crs")
    if crs is None:
        crs = cre.get("crs")
    if crs is None:
        crs = side.get("crs")

    confidence = verdict.get("confidence")
    if confidence is None and isinstance(verdict.get("details"), dict):
        confidence = verdict["details"].get("confidence")

    preference = (
        decision.get("mode")
        or job_mode
        or "automatic"
    )

    # Agent aggregates
    tele = agent_telemetry or []
    by_tier: Dict[str, Dict[str, float]] = {}
    for row in tele:
        tier = str(row.get("tier") or "medium")
        bucket = by_tier.setdefault(
            tier, {"count": 0, "carbon_g": 0.0, "latency_ms": 0.0, "confidence": 0.0}
        )
        bucket["count"] += 1
        bucket["carbon_g"] += float(row.get("carbon_estimate_g") or 0.0)
        bucket["latency_ms"] += float(row.get("latency_ms") or 0.0)
        bucket["confidence"] += float(row.get("confidence") or 0.0)
    carbon_by_agent = {}
    latency_by_agent = {}
    for tier, b in by_tier.items():
        n = max(1, int(b["count"]))
        carbon_by_agent[tier] = round(b["carbon_g"], 4)
        latency_by_agent[tier] = {
            "total_ms": round(b["latency_ms"], 1),
            "avg_ms": round(b["latency_ms"] / n, 1),
            "count": int(b["count"]),
        }

    details = verdict.get("details") if isinstance(verdict.get("details"), dict) else {}
    pass_rate = details.get("pass_rate")
    if pass_rate is None and details.get("fail_ratio") is not None:
        pass_rate = max(0.0, 1.0 - float(details["fail_ratio"]))

    avg_sem = verdict.get("semantic_similarity")
    avg_conf = confidence

    # Timeline from ingestion latency stages
    timeline = []
    if isinstance(ingestion_latency, dict):
        stages = ingestion_latency.get("stages_ms") or {}
        for name, ms in stages.items():
            timeline.append({"stage": name, "duration_ms": ms})

    budget = carbon_budget_g
    if budget is None:
        budget = carbon.get("carbon_budget_g")
    spent = carbon_spent_g
    if spent is None:
        spent = carbon.get("estimated_optimized_pipeline_emissions_g") or carbon.get(
            "actual_cost_gco2e"
        )
    remaining = carbon_remaining_g
    if remaining is None and budget is not None and spent is not None:
        remaining = max(0.0, float(budget) - float(spent))

    return {
        "crs": float(crs) if crs is not None else None,
        "document_type": decision.get("document_type") or None,
        "selected_model": decision.get("selected_model") or side.get("selected_model"),
        "tier": decision.get("tier") or side.get("tier"),
        "compile_tier": decision.get("compile_tier"),
        "retrieval_strategy": "Hybrid Dense + Sparse + Reranking",
        "escalation": {
            "required": escalation_required,
            "chunks_escalated": chunks_escalated,
            "details": escalations,
        },
        "carbon_optimization_applied": True,
        "latency_ms": float(latency_ms) if latency_ms is not None else None,
        "confidence": float(avg_conf) if avg_conf is not None else None,
        "reason_summary": decision.get("reason_summary") or side.get("reason") or "",
        "routing_preference": str(preference),
        "domain_risk": decision.get("domain_risk"),
        "policy_version": decision.get("policy_version"),
        "min_tier": decision.get("min_tier") or cre.get("min_tier"),
        # Adaptive pipeline extras
        "routing_distribution": dist if dist else {},
        "validation_pass_rate": float(pass_rate) if pass_rate is not None else None,
        "average_confidence": float(avg_conf) if avg_conf is not None else None,
        "average_semantic_similarity": float(avg_sem) if avg_sem is not None else None,
        "carbon_by_agent": carbon_by_agent,
        "latency_by_agent": latency_by_agent,
        "hierarchy": hierarchy or {},
        "compile_meta": compile_meta or {},
        "carbon_budget": {
            "budget_g": float(budget) if budget is not None else None,
            "spent_g": float(spent) if spent is not None else None,
            "remaining_g": float(remaining) if remaining is not None else None,
            "predicted_final_g": float(predicted_final_carbon_g)
            if predicted_final_carbon_g is not None
            else None,
        },
        "processing_timeline": timeline,
        "chunk_routing_sample": (chunk_routing or [])[:12],
        "document_structure_tree": tmeta.get("document_structure_tree") or [],
        "structure_diagnostics": tmeta.get("structure_diagnostics") or {},
        "pipeline_intelligence": intel,
        "document_profile": (
            lambda profile: (
                profile
                if not profile
                else {
                    **profile,
                    # Frontend CompactJobMetrics reads profile.complexity
                    "complexity": profile.get("complexity")
                    or profile.get("complexity_class"),
                    "document_type": profile.get("document_type")
                    or decision.get("document_type"),
                }
            )
        )(dict(intel.get("capability_profile") or {})),
        "processing_strategy": intel.get("strategy") or {},
        "intelligence_report": intel.get("report") or {},
        # Task 7 / 10 — additive DAG rollups & perf
        "carbon_rollups": (compile_meta or {}).get("carbon_rollups") or {},
        "perf_metrics": (compile_meta or {}).get("perf_metrics") or {},
        "dag_nodes_sample": list(((compile_meta or {}).get("dag_nodes") or {}).keys())[:40],
    }
