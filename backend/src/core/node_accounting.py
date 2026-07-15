"""Per-node energy / carbon / cost from real token counts (Boundary A)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from src.carbon.assumptions import J_PER_TOKEN_TYPICAL, PUE
from src.carbon.energy_model import apply_facility_overhead, energy_to_co2e_g, joules_to_kwh
from src.core.config import settings


# Rough USD / 1K tokens (comparative; not billed invoices)
_COST_PER_1K = {
    "light": 0.0001,
    "medium": 0.0004,
    "heavy": 0.0020,
}


def estimate_node_accounting(
    *,
    tier: str,
    tokens_in: int,
    tokens_out: int,
    latency_ms: float,
    grid_intensity: Optional[float] = None,
    model_id: Optional[str] = None,
) -> Dict[str, Any]:
    t = (tier or "medium").lower()
    if t not in ("light", "medium", "heavy"):
        t = "medium"
    intensity = float(
        grid_intensity
        if grid_intensity is not None
        else getattr(settings, "LOCAL_GRID_INTENSITY", 700)
        or 700
    )
    jpt = float(J_PER_TOKEN_TYPICAL.get(t, J_PER_TOKEN_TYPICAL["medium"]))
    tok = max(0, int(tokens_in or 0)) + max(0, int(tokens_out or 0))
    compute_j = tok * jpt
    facility_j = apply_facility_overhead(compute_j)
    energy_kwh = joules_to_kwh(facility_j)
    carbon_g = energy_to_co2e_g(energy_kwh, intensity)
    cost = (tok / 1000.0) * float(_COST_PER_1K.get(t, 0.0004))
    return {
        "tier": t,
        "model_id": model_id,
        "tokens_in": int(tokens_in or 0),
        "tokens_out": int(tokens_out or 0),
        "energy_joules": round(facility_j, 4),
        "energy_kwh": round(energy_kwh, 10),
        "carbon_g": round(carbon_g, 6),
        "cost_usd": round(cost, 8),
        "latency_ms": round(float(latency_ms or 0.0), 1),
        "grid_intensity": intensity,
        "pue": float(PUE),
    }
