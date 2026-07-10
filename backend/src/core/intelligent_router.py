"""
Intelligent Model Router

Filters by CRE min_tier, ranks by multi-objective utility, attaches fallbacks.
Routing preferences (automatic / fastest / lowest_cost / …) only adjust
optimization weights — they never bypass CRE capability floors or domain risk.
Legacy eco/balanced/performance/quality aliases remain for backward compatibility.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Optional

from src.core.config import settings
from src.core.cre import Tier, CREResult
from src.agents import models

log = logging.getLogger(__name__)

# Preference / mode weight profiles: cap, acc, rho, lat, cost, co2, avl
_BALANCED = {
    "cap": 0.30, "acc": 0.25, "rho": 0.10,
    "lat": 0.10, "cost": 0.10, "co2": 0.05, "avl": 0.10,
}
_ECO = {
    "cap": 0.28, "acc": 0.22, "rho": 0.10,
    "lat": 0.05, "cost": 0.10, "co2": 0.20, "avl": 0.05,
}
_QUALITY = {
    "cap": 0.32, "acc": 0.28, "rho": 0.10,
    "lat": 0.15, "cost": 0.05, "co2": 0.00, "avl": 0.10,
}
_FASTEST = {
    "cap": 0.28, "acc": 0.20, "rho": 0.10,
    "lat": 0.25, "cost": 0.05, "co2": 0.02, "avl": 0.10,
}
_LOWEST_COST = {
    "cap": 0.28, "acc": 0.22, "rho": 0.10,
    "lat": 0.08, "cost": 0.22, "co2": 0.05, "avl": 0.05,
}

MODE_WEIGHTS: Dict[str, Dict[str, float]] = {
    # Smart Routing UX preferences
    "automatic": dict(_BALANCED),
    "fastest": dict(_FASTEST),
    "lowest_cost": dict(_LOWEST_COST),
    "lowest_carbon": dict(_ECO),
    "highest_quality": dict(_QUALITY),
    # Legacy aliases
    "eco": dict(_ECO),
    "balanced": dict(_BALANCED),
    "performance": dict(_QUALITY),
    "quality": dict(_QUALITY),
}

# Normalize odd client strings → canonical preference keys
_MODE_ALIASES = {
    "auto": "automatic",
    "smart": "automatic",
    "smart_routing": "automatic",
    "max quality": "highest_quality",
    "max_quality": "highest_quality",
    "prefer_fastest": "fastest",
    "prefer_lowest_cost": "lowest_cost",
    "prefer_lowest_carbon": "lowest_carbon",
    "prefer_highest_quality": "highest_quality",
}


def normalize_routing_preference(mode: Optional[str]) -> str:
    """Map client mode/preference string to a MODE_WEIGHTS key."""
    key = (mode or "automatic").strip().lower().replace("-", "_")
    key = _MODE_ALIASES.get(key, key)
    if key not in MODE_WEIGHTS:
        return "automatic"
    return key

# Relative profiles per tier (normalized later in ranking)
TIER_PROFILES = {
    Tier.LIGHT: {
        "capacity": 0.30,
        "expected_accuracy": 0.55,
        "latency_norm": 0.20,  # lower is better → we subtract
        "cost_norm": 0.15,
        "co2_norm": 0.15,
    },
    Tier.MEDIUM: {
        "capacity": 0.65,
        "expected_accuracy": 0.78,
        "latency_norm": 0.45,
        "cost_norm": 0.45,
        "co2_norm": 0.45,
    },
    Tier.HEAVY: {
        "capacity": 0.95,
        "expected_accuracy": 0.92,
        "latency_norm": 0.80,
        "cost_norm": 0.85,
        "co2_norm": 0.85,
    },
}


@dataclass
class ModelCandidate:
    model_id: str
    tier: str
    is_primary: bool = True


@dataclass
class RoutingDecision:
    selected_model: str
    tier: str
    compile_tier: str
    fallbacks: List[str]
    compile_fallbacks: List[str]
    utility: float
    utility_ranking: List[Dict[str, Any]]
    mode: str
    weights: Dict[str, float]
    crs: float
    crs_raw: float
    domain_floor: float
    min_tier: str
    document_type: str
    domain_risk: Dict[str, str]
    signals: Dict[str, Any]
    reason_summary: str
    policy_version: str
    escalations: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _catalog() -> List[ModelCandidate]:
    cats: List[ModelCandidate] = []
    lights = settings.light_models()
    mediums = settings.medium_models()
    heavies = settings.heavy_models()
    for i, m in enumerate(lights):
        cats.append(ModelCandidate(m, Tier.LIGHT.value, is_primary=(i == 0)))
    for i, m in enumerate(mediums):
        cats.append(ModelCandidate(m, Tier.MEDIUM.value, is_primary=(i == 0)))
    for i, m in enumerate(heavies):
        cats.append(ModelCandidate(m, Tier.HEAVY.value, is_primary=(i == 0)))
    return cats


def _availability(model_id: str) -> float:
    # Circuit: if NIM client missing, nothing available
    if models.get_nim_client() is None:
        return 0.0
    # Could extend with per-model health cache
    return 1.0


def _cap_fit(tier: Tier, crs: float, min_tier: Tier) -> float:
    if tier.rank() < min_tier.rank():
        return float("-inf")
    capacity = TIER_PROFILES[tier]["capacity"]
    if capacity + 1e-6 < crs:
        # Soft penalty if capacity slightly under CRS but tier OK
        return max(0.0, 1.0 - (crs - capacity) * 2)
    return 1.0


def utility(
    candidate: ModelCandidate,
    crs: float,
    min_tier: Tier,
    features: Dict[str, Any],
    weights: Dict[str, float],
) -> float:
    tier = Tier.from_str(candidate.tier)
    cap = _cap_fit(tier, crs, min_tier)
    if cap == float("-inf"):
        return float("-inf")

    prof = TIER_PROFILES[tier]
    rho = float(features.get("retrieval_confidence", 0.7))
    carbon = features.get("carbon") or {}
    intensity = float(carbon.get("grid_carbon_intensity_gco2_kwh", settings.LOCAL_GRID_INTENSITY))
    # Normalize intensity ~ [200, 800] → [0, 1]
    co2_scale = max(0.0, min(1.0, (intensity - 200) / 600))
    co2_norm = prof["co2_norm"] * (0.5 + 0.5 * co2_scale)

    avl = _availability(candidate.model_id)
    # Prefer primaries slightly
    primary_bonus = 0.02 if candidate.is_primary else 0.0

    U = (
        weights["cap"] * cap
        + weights["acc"] * prof["expected_accuracy"]
        + weights["rho"] * rho
        - weights["lat"] * prof["latency_norm"]
        - weights["cost"] * prof["cost_norm"]
        - weights["co2"] * co2_norm
        + weights["avl"] * avl
        + primary_bonus
    )
    return U


def models_for_tier(tier: Tier) -> List[str]:
    if tier == Tier.LIGHT:
        return settings.light_models()
    if tier == Tier.MEDIUM:
        return settings.medium_models()
    return settings.heavy_models()


def route(
    cre: CREResult,
    features: Dict[str, Any],
    mode: str = "automatic",
) -> RoutingDecision:
    mode_key = normalize_routing_preference(mode)
    weights = MODE_WEIGHTS[mode_key]

    min_tier = Tier.from_str(cre.min_tier)
    compile_tier = Tier.from_str(cre.compile_tier)

    ranking: List[Dict[str, Any]] = []
    best: Optional[ModelCandidate] = None
    best_u = float("-inf")

    for cand in _catalog():
        u = utility(cand, cre.crs, min_tier, features, weights)
        if u == float("-inf"):
            continue
        ranking.append({"model": cand.model_id, "tier": cand.tier, "U": round(u, 4)})
        if u > best_u:
            best_u = u
            best = cand

    ranking.sort(key=lambda x: x["U"], reverse=True)

    if best is None:
        # Fail closed → Heavy
        log.warning("Router: no eligible models; fail-closed to Heavy")
        best = ModelCandidate(settings.HEAVY_MODEL_PRIMARY, Tier.HEAVY.value, True)
        best_u = 0.0
        min_tier = Tier.HEAVY
        compile_tier = Tier.HEAVY

    selected_tier = Tier.from_str(best.tier)
    fallbacks = [m for m in models_for_tier(selected_tier) if m != best.model_id]
    # Ensure selected is first in chain
    map_chain = [best.model_id] + fallbacks
    compile_chain = models_for_tier(compile_tier)

    carbon = features.get("carbon") or {}
    reason = (
        f"Document Type = {features.get('document_type')}; "
        f"Reasoning = {features.get('reasoning_score')}; "
        f"Retrieval Confidence = {features.get('retrieval_confidence')}; "
        f"OCR Confidence = {features.get('ocr_confidence')}; "
        f"Carbon = {carbon.get('grid_carbon_intensity_gco2_kwh')} gCO2/kWh; "
        f"Routing Preference = {mode_key}; Selected = {best.model_id} ({selected_tier.value})"
    )

    decision = RoutingDecision(
        selected_model=best.model_id,
        tier=selected_tier.value,
        compile_tier=compile_tier.value,
        fallbacks=map_chain,
        compile_fallbacks=compile_chain,
        utility=round(best_u, 4),
        utility_ranking=ranking[:8],
        mode=mode_key,
        weights=weights,
        crs=cre.crs,
        crs_raw=cre.crs_raw,
        domain_floor=cre.domain_floor,
        min_tier=cre.min_tier,
        document_type=str(features.get("document_type")),
        domain_risk={
            "level": str(features.get("risk_level")),
            "label": str(features.get("domain_label")),
        },
        signals={
            "reasoning": features.get("reasoning_score"),
            "structural": features.get("structural_score"),
            "coherence": features.get("coherence_score"),
            "retrieval_confidence": features.get("retrieval_confidence"),
            "ocr_confidence": features.get("ocr_confidence"),
            "carbon_gco2_kwh": carbon.get("grid_carbon_intensity_gco2_kwh"),
            "latency_budget_ms": (features.get("runtime") or {}).get("estimated_latency_budget_ms"),
        },
        reason_summary=reason,
        policy_version=cre.policy_version,
    )
    log.info(f"Router: {reason}")
    return decision


def escalate_decision(decision: RoutingDecision, reason_codes: List[str]) -> RoutingDecision:
    """Bump map tier by exactly +1; refresh fallbacks."""
    current = Tier.from_str(decision.tier)
    nxt = current.next()
    if nxt is None:
        decision.escalations.append({
            "reason": reason_codes,
            "from": current.value,
            "to": None,
            "note": "already_at_heavy",
        })
        return decision

    chain = models_for_tier(nxt)
    decision.tier = nxt.value
    decision.selected_model = chain[0]
    decision.fallbacks = chain
    # Compile at least the new tier
    decision.compile_tier = Tier.max_of(Tier.from_str(decision.compile_tier), nxt).value
    decision.compile_fallbacks = models_for_tier(Tier.from_str(decision.compile_tier))
    decision.escalations.append({
        "reason": reason_codes,
        "from": current.value,
        "to": nxt.value,
        "selected_model": decision.selected_model,
    })
    decision.reason_summary += f" | ESCALATED +1 → {nxt.value} ({decision.selected_model})"
    log.info(f"Escalation: {current.value} → {nxt.value} reasons={reason_codes}")
    return decision
