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
) -> Dict[str, Any]:
    decision = routing_decision or {}
    cre = cre_result or {}
    carbon = carbon_report or {}
    verdict = validation_verdict or {}
    side = carbon.get("routing") if isinstance(carbon.get("routing"), dict) else {}

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
        "confidence": float(confidence) if confidence is not None else None,
        "reason_summary": decision.get("reason_summary") or side.get("reason") or "",
        "routing_preference": str(preference),
        "domain_risk": decision.get("domain_risk"),
        "policy_version": decision.get("policy_version"),
        "min_tier": decision.get("min_tier") or cre.get("min_tier"),
    }
