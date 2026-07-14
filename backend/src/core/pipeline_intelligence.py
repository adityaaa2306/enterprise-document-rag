"""
Pipeline Intelligence — capability analysis, strategy selection, explainability.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from src.core.config import settings
from src.core.document_capability import (
    DocumentCapabilityProfile,
    analyze_document_capability,
)
from src.core.strategy_selector import ProcessingStrategy, select_processing_strategy

log = logging.getLogger(__name__)


def build_explainability_report(
    profile: DocumentCapabilityProfile,
    strategy: ProcessingStrategy,
    *,
    routing_distribution: Optional[Dict[str, Any]] = None,
    cre_result: Optional[Dict[str, Any]] = None,
    carbon_intensity: Optional[float] = None,
    escalations: Optional[Dict[str, Any]] = None,
    compile_meta: Optional[Dict[str, Any]] = None,
    validation: Optional[Dict[str, Any]] = None,
    latency_by_stage: Optional[Dict[str, float]] = None,
    carbon_by_stage: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    dist = routing_distribution or {}
    n = int(profile.chunk_count or dist.get("total") or 0)
    # Rough priors for expected quality / cost
    light = int(dist.get("light") or 0)
    medium = int(dist.get("medium") or 0)
    heavy = int(dist.get("heavy") or 0)
    if n and not (light + medium + heavy):
        medium = n
    expected_quality = 0.0
    if n:
        expected_quality = (
            light * 0.88 + medium * 0.95 + heavy * 0.97
        ) / max(1, light + medium + heavy)
    expected_map_carbon = light * 0.08 + medium * 0.18 + heavy * 0.41
    expected_latency_s = (
        (light * 0.8 + medium * 1.6 + heavy * 3.2)
        / max(1, int(getattr(settings, "MAP_MAX_WORKERS", 3) or 3))
    )

    return {
        "why_chunk_sizes": (
            f"Structure parser produced {profile.chunk_count} map units "
            f"(avg {profile.average_section_tokens:.0f} tok). Strategy "
            f"'{strategy.strategy_id}' targets ~{strategy.chunk_target_tokens} tok "
            f"packing band without force-cap."
        ),
        "why_strategy": list(strategy.reasons),
        "why_models": (
            "Per-chunk tier = f(complexity, importance, technicality, CRE floor, "
            "carbon budget, grid intensity, user mode). Grid intensity never acts alone."
        ),
        "why_escalations": (
            escalations
            or {
                "policy": f"max_escalations={strategy.max_escalations}, "
                f"max_chunks={strategy.max_escalate_chunks}",
                "rule": "Escalate only low-confidence / failed QVA chunks up the ladder",
            }
        ),
        "why_compile_depth": (
            f"scale={profile.document_scale} → compile_depth={strategy.compile_depth_label}, "
            f"fan_in={strategy.hierarchy_fan_in}, max_depth={strategy.hierarchy_max_depth}"
        ),
        "estimated_carbon_g": round(expected_map_carbon, 3),
        "estimated_latency_s": round(expected_latency_s, 1),
        "estimated_map_api_calls": n,
        "expected_quality": round(expected_quality, 3),
        "carbon_intensity_gco2_kwh": carbon_intensity,
        "cre": cre_result or {},
        "routing_mix": {"light": light, "medium": medium, "heavy": heavy},
        "compile_meta": compile_meta or {},
        "validation": validation or {},
        "latency_by_stage": latency_by_stage or {},
        "carbon_by_stage": carbon_by_stage or {},
        "accuracy_estimate": round(expected_quality, 3),
    }


def plan_pipeline_intelligence(
    *,
    chunks: List[Any],
    features: Dict[str, Any],
    chunk_features: List[Dict[str, Any]],
    triage_meta: Optional[Dict[str, Any]] = None,
    chunk_parents: Optional[List[Any]] = None,
    job_mode: str = "automatic",
    carbon_intensity: Optional[float] = None,
) -> Dict[str, Any]:
    profile = analyze_document_capability(
        chunks,
        features=features,
        chunk_features=chunk_features,
        triage_meta=triage_meta,
        chunk_parents=chunk_parents,
    )
    intensity = carbon_intensity
    if intensity is None:
        intensity = float(getattr(settings, "LOCAL_GRID_INTENSITY", 700) or 700)
    strategy = select_processing_strategy(
        profile, job_mode=job_mode, carbon_intensity=intensity
    )
    report = build_explainability_report(
        profile, strategy, carbon_intensity=intensity
    )
    log.info(
        "PipelineIntelligence: scale=%s complexity=%s strategy=%s map_mode=%s "
        "compile=%s fan_in=%s",
        profile.document_scale,
        profile.complexity_class,
        strategy.strategy_id,
        strategy.map_mode,
        strategy.compile_depth_label,
        strategy.hierarchy_fan_in,
    )
    return {
        "policy_version": str(
            getattr(settings, "PIPELINE_INTEL_POLICY_VERSION", "intel-v1")
        ),
        "capability_profile": profile.to_dict(),
        "strategy": strategy.to_dict(),
        "report": report,
    }


def enrich_report_after_run(
    intel: Dict[str, Any],
    *,
    routing_distribution: Optional[Dict[str, Any]] = None,
    cre_result: Optional[Dict[str, Any]] = None,
    escalations: Optional[Dict[str, Any]] = None,
    compile_meta: Optional[Dict[str, Any]] = None,
    validation: Optional[Dict[str, Any]] = None,
    latency_by_stage: Optional[Dict[str, float]] = None,
    carbon_by_stage: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Update explainability report with post-run telemetry (immutable-ish copy)."""
    from dataclasses import fields

    out = dict(intel or {})
    raw_profile = dict(out.get("capability_profile") or {})
    allowed = {f.name for f in fields(DocumentCapabilityProfile)}
    profile = DocumentCapabilityProfile(
        **{k: v for k, v in raw_profile.items() if k in allowed}
    )
    from src.core.strategy_selector import ProcessingStrategy

    strat_d = out.get("strategy") or {}
    strategy = ProcessingStrategy(
        strategy_id=str(strat_d.get("strategy_id") or "unknown"),
        map_mode=str(strat_d.get("map_mode") or "map_reduce"),
        chunk_target_tokens=int(strat_d.get("chunk_target_tokens") or 800),
        hierarchy_fan_in=int(strat_d.get("hierarchy_fan_in") or 8),
        hierarchy_max_depth=int(strat_d.get("hierarchy_max_depth") or 4),
        skip_regional_below=int(strat_d.get("skip_regional_below") or 8),
        compile_depth_label=str(strat_d.get("compile_depth_label") or "regional"),
        medium_first=bool(strat_d.get("medium_first", True)),
        compile_tier_hint=str(strat_d.get("compile_tier_hint") or "medium"),
        retrieval_strategy=str(strat_d.get("retrieval_strategy") or "hybrid"),
        verification_strategy=str(strat_d.get("verification_strategy") or "standard"),
        qva_confidence_threshold=float(strat_d.get("qva_confidence_threshold") or 0.6),
        qva_compile_threshold=float(strat_d.get("qva_compile_threshold") or 0.58),
        max_escalations=int(strat_d.get("max_escalations") or 2),
        max_escalate_chunks=int(strat_d.get("max_escalate_chunks") or 8),
        carbon_budget_g=float(strat_d.get("carbon_budget_g") or 40),
        prefer_light_under_carbon=bool(strat_d.get("prefer_light_under_carbon", True)),
        heavy_quality_gain_min=float(strat_d.get("heavy_quality_gain_min") or 0.02),
        reasons=list(strat_d.get("reasons") or []),
    )
    out["report"] = build_explainability_report(
        profile,
        strategy,
        routing_distribution=routing_distribution,
        cre_result=cre_result,
        carbon_intensity=(out.get("report") or {}).get("carbon_intensity_gco2_kwh"),
        escalations=escalations,
        compile_meta=compile_meta,
        validation=validation,
        latency_by_stage=latency_by_stage,
        carbon_by_stage=carbon_by_stage,
    )
    return out
