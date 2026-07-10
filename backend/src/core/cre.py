"""
Capability Requirement Engine (CRE)

CRS = minimum model capability required to successfully complete the task.
Not document difficulty, readability, or length.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any, Dict, Optional

from src.core.config import settings

log = logging.getLogger(__name__)


class Tier(str, Enum):
    LIGHT = "light"
    MEDIUM = "medium"
    HEAVY = "heavy"

    def rank(self) -> int:
        return {Tier.LIGHT: 0, Tier.MEDIUM: 1, Tier.HEAVY: 2}[self]

    def next(self) -> Optional["Tier"]:
        order = [Tier.LIGHT, Tier.MEDIUM, Tier.HEAVY]
        i = order.index(self)
        return order[i + 1] if i + 1 < len(order) else None

    @classmethod
    def from_str(cls, value: str) -> "Tier":
        return cls(value.lower().strip())

    @classmethod
    def max_of(cls, a: "Tier", b: "Tier") -> "Tier":
        return a if a.rank() >= b.rank() else b


# Domain floors: CRS floor + minimum tier
DOMAIN_FLOORS: Dict[str, Dict[str, Any]] = {
    "medical": {"crs_floor": 0.70, "min_tier": Tier.HEAVY},
    "legal": {"crs_floor": 0.55, "min_tier": Tier.MEDIUM},
    "financial": {"crs_floor": 0.45, "min_tier": Tier.MEDIUM},
    "regulatory": {"crs_floor": 0.45, "min_tier": Tier.MEDIUM},
}

TIER_THRESHOLDS = {
    "light_max": 0.35,   # CRS < 0.35 → Light
    "medium_max": 0.65,  # CRS < 0.65 → Medium else Heavy
}


@dataclass
class CREResult:
    crs_raw: float
    crs: float
    domain_floor: float
    min_tier: str
    compile_tier: str
    weights: Dict[str, float]
    policy_version: str
    rationale: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def domain_floor(domain_label: str, risk_level: str) -> tuple[float, Tier]:
    """
    Returns (crs_floor, min_tier) from domain + risk.
    High-risk domains enforce floors regardless of other scores.
    """
    label = (domain_label or "general").lower()
    risk = (risk_level or "general").lower()

    if label in DOMAIN_FLOORS:
        spec = DOMAIN_FLOORS[label]
        return float(spec["crs_floor"]), spec["min_tier"]

    if risk == "high":
        return 0.45, Tier.MEDIUM
    if risk == "medium":
        return 0.35, Tier.MEDIUM
    return 0.0, Tier.LIGHT


def tier_from_crs(crs: float) -> Tier:
    if crs < TIER_THRESHOLDS["light_max"]:
        return Tier.LIGHT
    if crs < TIER_THRESHOLDS["medium_max"]:
        return Tier.MEDIUM
    return Tier.HEAVY


def compute_crs(features: Dict[str, Any]) -> CREResult:
    """
    CRS_raw = w_R·R + w_S·S + w_X·X + w_ρ·(1 − ρ)
    CRS = max(CRS_raw, Floor(domain, risk))
    """
    w_r = settings.CRE_WEIGHT_REASONING
    w_s = settings.CRE_WEIGHT_STRUCTURAL
    w_x = settings.CRE_WEIGHT_COHERENCE
    w_rho = settings.CRE_WEIGHT_RETRIEVAL

    R = _clamp01(features.get("reasoning_score", 0.4))
    S = _clamp01(features.get("structural_score", 0.3))
    X = _clamp01(features.get("coherence_score", 0.3))
    rho = _clamp01(features.get("retrieval_confidence", 0.7))

    crs_raw = _clamp01(w_r * R + w_s * S + w_x * X + w_rho * (1.0 - rho))

    domain = features.get("domain_label", "general")
    risk = features.get("risk_level", "general")
    floor_val, floor_tier = domain_floor(domain, risk)

    crs = max(crs_raw, floor_val)
    crs_tier = tier_from_crs(crs)
    min_tier = Tier.max_of(crs_tier, floor_tier)

    # Compile prefers Heavy when coherence demand or chunk count is high
    chunk_count = int(features.get("chunk_count", 0) or 0)
    compile_tier = min_tier
    if X >= 0.55 or chunk_count >= settings.CRE_HEAVY_COMPILE_CHUNK_THRESHOLD:
        compile_tier = Tier.max_of(min_tier, Tier.HEAVY)
    elif X >= 0.40 or chunk_count >= 12:
        compile_tier = Tier.max_of(min_tier, Tier.MEDIUM)

    rationale = (
        f"CRS_raw={crs_raw:.3f} floor={floor_val:.3f} CRS={crs:.3f} "
        f"(R={R:.2f} S={S:.2f} X={X:.2f} ρ={rho:.2f}) "
        f"domain={domain}/{risk} → min_tier={min_tier.value} compile={compile_tier.value}"
    )
    log.info(f"CRE: {rationale}")

    return CREResult(
        crs_raw=round(crs_raw, 4),
        crs=round(crs, 4),
        domain_floor=floor_val,
        min_tier=min_tier.value,
        compile_tier=compile_tier.value,
        weights={"R": w_r, "S": w_s, "X": w_x, "rho": w_rho},
        policy_version=settings.CRE_POLICY_VERSION,
        rationale=rationale,
    )
