"""
Per-chunk adaptive router (Light / Medium / Heavy).

Combines chunk features, document CRE floors, carbon budget, and expected
quality/carbon tradeoffs. Prefer Light; Heavy only when justified.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from src.core.config import settings

log = logging.getLogger(__name__)

_TIER_RANK = {"light": 0, "medium": 1, "heavy": 2, "large": 2}
_RANK_TIER = {0: "light", 1: "medium", 2: "heavy"}

# Rough expected quality / carbon (g) per chunk for decision support.
_TIER_EXPECT = {
    "light": {"quality": 0.88, "carbon_g": 0.08, "latency_ms": 800},
    "medium": {"quality": 0.95, "carbon_g": 0.18, "latency_ms": 1600},
    "heavy": {"quality": 0.97, "carbon_g": 0.41, "latency_ms": 3200},
}


@dataclass
class ChunkRouteDecision:
    chunk_index: int
    tier: str
    model: str
    reason: str
    expected_quality: float
    expected_carbon_g: float
    expected_latency_ms: float
    complexity: float = 0.0
    importance: float = 0.0
    features_snapshot: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _max_tier(a: str, b: str) -> str:
    return _RANK_TIER[max(_TIER_RANK.get(a, 1), _TIER_RANK.get(b, 1))]


def _min_tier_floor(cre_min: Optional[str], domain_risk: Any) -> str:
    floor = (cre_min or "light").lower()
    if floor not in _TIER_RANK:
        floor = "light"
    if isinstance(domain_risk, dict):
        risk = str(
            domain_risk.get("label")
            or domain_risk.get("domain")
            or domain_risk.get("risk_level")
            or ""
        ).lower()
    else:
        risk = str(domain_risk or "").lower()
    if risk in ("medical", "clinical"):
        floor = _max_tier(floor, "heavy")
    elif risk in ("legal", "financial"):
        floor = _max_tier(floor, "medium")
    return floor


def _feature_suggested_tier(feat: Mapping[str, Any]) -> tuple[str, List[str]]:
    reasons: List[str] = []
    complexity = float(feat.get("complexity") or 0.0)
    importance = float(feat.get("importance") or 0.0)
    tech = float(feat.get("technical_density") or 0.0)
    eqs = int(feat.get("equation_count") or 0)
    section = str(feat.get("section_type") or "narrative")
    tokens = int(feat.get("token_count") or 0)

    score = (
        0.35 * complexity
        + 0.30 * importance
        + 0.20 * tech
        + 0.10 * min(1.0, eqs / 4.0)
        + 0.05 * min(1.0, tokens / 1500.0)
    )
    if section in ("legal", "equation_heavy"):
        score += 0.12
        reasons.append(f"section_type={section}")
    if eqs > 0:
        reasons.append(f"contains equations ({eqs})")
    if importance >= 0.85:
        reasons.append(f"high importance ({importance:.2f})")
    if complexity >= 0.75:
        reasons.append(f"high complexity ({complexity:.2f})")

    if score >= 0.72 or (complexity >= 0.82 and importance >= 0.75):
        tier = "heavy"
        if not reasons:
            reasons.append("high reasoning complexity")
    elif score >= 0.42 or section in ("technical", "table"):
        tier = "medium"
        if not reasons:
            reasons.append("technical / moderate complexity")
    else:
        tier = "light"
        if not reasons:
            reasons.append("simple / low-density content")
    return tier, reasons


def _model_for_tier(tier: str, routing_decision: Optional[Mapping[str, Any]]) -> str:
    rd = routing_decision or {}
    if tier == (rd.get("tier") or "") and rd.get("selected_model"):
        return str(rd["selected_model"])
    if tier == "light":
        return (settings.light_models() or ["light"])[0]
    if tier == "heavy":
        return (settings.heavy_models() or ["heavy"])[0]
    return (settings.medium_models() or ["medium"])[0]


def route_chunks(
    chunk_features: Sequence[Mapping[str, Any]],
    *,
    cre_result: Optional[Mapping[str, Any]] = None,
    routing_decision: Optional[Mapping[str, Any]] = None,
    carbon_remaining_g: Optional[float] = None,
    budget_enabled: Optional[bool] = None,
    strategy: Optional[Mapping[str, Any]] = None,
    carbon_intensity: Optional[float] = None,
) -> List[ChunkRouteDecision]:
    """
    Assign Light/Medium/Heavy per chunk with explanations.

    Uses chunk complexity AND carbon intensity / strategy — never grid alone.
    """
    cre = cre_result or {}
    rd = routing_decision or {}
    strat = strategy or {}
    floor = _min_tier_floor(cre.get("min_tier") or rd.get("min_tier"), rd.get("domain_risk"))
    use_budget = (
        bool(settings.CARBON_BUDGET_ENABLED)
        if budget_enabled is None
        else bool(budget_enabled)
    )
    remaining = (
        float(carbon_remaining_g)
        if carbon_remaining_g is not None
        else float(strat.get("carbon_budget_g") or settings.CARBON_BUDGET_G)
    )
    gain_min = float(
        strat.get("heavy_quality_gain_min")
        if strat.get("heavy_quality_gain_min") is not None
        else getattr(settings, "HEAVY_QUALITY_GAIN_MIN", 0.02) or 0.02
    )
    prefer_light = bool(strat.get("prefer_light_under_carbon", False))
    intensity = float(
        carbon_intensity
        if carbon_intensity is not None
        else getattr(settings, "LOCAL_GRID_INTENSITY", 700) or 700
    )

    decisions: List[ChunkRouteDecision] = []
    spent_pred = 0.0

    for feat in chunk_features:
        idx = int(feat.get("chunk_index") or 0)
        suggested, reasons = _feature_suggested_tier(feat)
        tier = _max_tier(suggested, floor)

        # Carbon-aware: if Heavy adds negligible quality vs Medium, stay Medium.
        if tier == "heavy":
            q_h = _TIER_EXPECT["heavy"]["quality"]
            q_m = _TIER_EXPECT["medium"]["quality"]
            if (q_h - q_m) < gain_min and floor != "heavy":
                tier = "medium"
                reasons.append("heavy quality gain negligible → medium")

        # Grid intensity bias (never sole decision)
        if prefer_light and intensity >= 500 and tier == "heavy" and floor != "heavy":
            tier = "medium"
            reasons.append(
                f"high grid intensity ({intensity:.0f}) + prefer_light → medium"
            )
        if prefer_light and intensity >= 650 and floor == "light":
            complexity = float(feat.get("complexity") or 0)
            if tier == "medium" and complexity < 0.55:
                tier = "light"
                reasons.append("high grid + low complexity → light")

        # Budget pressure: demote when predicted spend would exhaust budget.
        if use_budget and remaining < float("inf"):
            pred = spent_pred + float(_TIER_EXPECT[tier]["carbon_g"])
            if pred > remaining and tier != "light":
                demoted = "medium" if tier == "heavy" else "light"
                if _TIER_RANK[demoted] >= _TIER_RANK[floor]:
                    reasons.append(
                        f"carbon budget pressure ({remaining - spent_pred:.2f}g left) → {demoted}"
                    )
                    tier = demoted
                elif tier == "heavy" and _TIER_RANK["medium"] >= _TIER_RANK[floor]:
                    tier = "medium"
                    reasons.append("carbon budget → medium instead of heavy")

        expect = _TIER_EXPECT[tier]
        spent_pred += float(expect["carbon_g"])
        model = _model_for_tier(tier, rd)
        reason = (
            f"Assigned → {tier.title()}. "
            + "; ".join(reasons)
            + f". Floor={floor}. Grid={intensity:.0f} gCO2/kWh."
        )
        decisions.append(
            ChunkRouteDecision(
                chunk_index=idx,
                tier=tier,
                model=model,
                reason=reason,
                expected_quality=float(expect["quality"]),
                expected_carbon_g=float(expect["carbon_g"]),
                expected_latency_ms=float(expect["latency_ms"]),
                complexity=float(feat.get("complexity") or 0.0),
                importance=float(feat.get("importance") or 0.0),
                features_snapshot={
                    k: feat.get(k)
                    for k in (
                        "section_type",
                        "equation_count",
                        "technical_density",
                        "named_entity_density",
                        "token_count",
                    )
                },
            )
        )

    light = sum(1 for d in decisions if d.tier == "light")
    med = sum(1 for d in decisions if d.tier == "medium")
    heavy = sum(1 for d in decisions if d.tier == "heavy")
    log.info(
        "chunk_router: n=%s light=%s medium=%s heavy=%s floor=%s predicted_g=%.2f",
        len(decisions),
        light,
        med,
        heavy,
        floor,
        spent_pred,
    )
    return decisions


def routing_distribution(decisions: Sequence[ChunkRouteDecision]) -> Dict[str, Any]:
    n = max(1, len(decisions))
    counts = {"light": 0, "medium": 0, "heavy": 0}
    for d in decisions:
        key = d.tier if d.tier in counts else "medium"
        counts[key] += 1
    return {
        "total": len(decisions),
        "light": counts["light"],
        "medium": counts["medium"],
        "heavy": counts["heavy"],
        "light_pct": round(100.0 * counts["light"] / n, 1),
        "medium_pct": round(100.0 * counts["medium"] / n, 1),
        "heavy_pct": round(100.0 * counts["heavy"] / n, 1),
        "predicted_carbon_g": round(
            sum(d.expected_carbon_g for d in decisions), 4
        ),
    }
