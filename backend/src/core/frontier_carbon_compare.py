"""
Frontier-model comparison visualization.

Scales each model's estimated CO₂e from the workflow baseline
(energy × Electricity Maps intensity). Never uses chunks × grams.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from src.carbon.accounting import METHODOLOGY_TEXT as CARBON_METHODOLOGY

# Relative inference intensity vs conventional GPT-4o-mini-class baseline (1.0).
# Tuned so document-scale estimates stay in a realistic band (~20–80 g CO₂e
# at ~500–600 gCO₂e/kWh), not legacy chunk×grams explosions.
FRONTIER_RELATIVE_INTENSITY: Tuple[Tuple[str, float], ...] = (
    ("GPT-o3", 2.20),
    ("GPT-4", 1.90),
    ("Llama 4 Behemoth", 2.00),
    ("Claude 4 Opus", 1.70),
    ("GPT-4o", 1.40),
    ("Gemini 2.5 Pro", 1.35),
    ("Llama 4 Maverick", 1.05),
    ("Gemma 3", 0.90),
)

OUR_SYSTEM_NAME = "Green Agentic Document Processing System"
OUR_SYSTEM_TAGLINE = "Smart Carbon-Aware Routing"

COMPARISON_METHODOLOGY = (
    "Frontier model bars are comparative estimates: each value is this "
    "document's conventional baseline energy × a published-style relative "
    "inference factor × the same live Electricity Maps grid intensity used "
    "for our system. Our system uses measured workflow energy (embedding, "
    "retrieval, routing, inference, generation) × that intensity. "
    "Values are for comparison and visualization, not exact lifecycle LCAs. "
    + CARBON_METHODOLOGY
)

METHODOLOGY_TEXT = COMPARISON_METHODOLOGY

BADGE_TOP_N = 3


def _round1(value: float) -> float:
    return round(float(value), 1)


def _round4(value: float) -> float:
    return round(float(value), 4)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _resolve_baseline_co2(data: Mapping[str, Any]) -> float:
    """Prefer energy×intensity; never invent from chunk counts."""
    breakdown = data.get("breakdown") if isinstance(data.get("breakdown"), dict) else {}
    baseline = _safe_float(data.get("baseline_cost_gco2e"))
    if baseline <= 0:
        baseline = _safe_float(breakdown.get("baseline_co2e_g"))
    if baseline > 0:
        return baseline

    energy_kwh = _safe_float(data.get("baseline_energy_kwh"))
    if energy_kwh <= 0:
        energy_kwh = _safe_float(breakdown.get("baseline_energy_kwh"))
    intensity = _safe_float(data.get("local_grid_gco2_kwh"))
    if intensity <= 0:
        intensity = _safe_float(breakdown.get("grid_carbon_intensity_gco2_kwh"))
    if energy_kwh > 0 and intensity > 0:
        return energy_kwh * intensity
    return 0.0


def build_frontier_comparison(
    carbon_data: Optional[Mapping[str, Any]],
    *,
    model_factors: Optional[Sequence[Tuple[str, float]]] = None,
    badge_top_n: int = BADGE_TOP_N,
) -> Dict[str, Any]:
    data = dict(carbon_data or {})
    baseline = _resolve_baseline_co2(data)
    actual = _safe_float(data.get("actual_cost_gco2e"))
    if actual <= 0:
        breakdown = data.get("breakdown") if isinstance(data.get("breakdown"), dict) else {}
        actual = _safe_float(breakdown.get("actual_co2e_g"))
    saved = _safe_float(data.get("carbon_saved_grams"))
    if saved <= 0 and baseline > 0:
        saved = max(0.0, baseline - actual)
    efficiency = _safe_float(data.get("efficiency_percent"))
    if efficiency <= 0 and baseline > 0:
        efficiency = min(100.0, (saved / baseline) * 100.0)
    breakdown = data.get("breakdown") if isinstance(data.get("breakdown"), dict) else {}

    # Guard against stale chunk×grams payloads still sitting in old jobs.
    if baseline > 150:
        energy_kwh = _safe_float(data.get("baseline_energy_kwh")) or _safe_float(
            breakdown.get("baseline_energy_kwh")
        )
        intensity = _safe_float(data.get("local_grid_gco2_kwh")) or _safe_float(
            breakdown.get("grid_carbon_intensity_gco2_kwh")
        )
        if energy_kwh > 0 and intensity > 0:
            rebuilt = energy_kwh * intensity
            if 0 < rebuilt < baseline:
                baseline = rebuilt

    factors = list(model_factors or FRONTIER_RELATIVE_INTENSITY)
    comparison_models: List[Dict[str, Any]] = []

    for model_name, factor in factors:
        estimated = baseline * float(factor)
        saved_g = estimated - actual
        reduction = (saved_g / estimated) * 100.0 if estimated > 0 else 0.0
        comparison_models.append(
            {
                "model": model_name,
                "relative_factor": float(factor),
                "estimated_gco2e": _round1(estimated),
                "saved_gco2e": _round1(saved_g),
                "reduction_percent": _round1(reduction),
            }
        )

    ranked = sorted(
        comparison_models,
        key=lambda row: (row["reduction_percent"], row["saved_gco2e"]),
        reverse=True,
    )
    badges: List[str] = []
    seen_factors: set = set()
    for row in ranked:
        if len(badges) >= max(0, int(badge_top_n)):
            break
        factor = row.get("relative_factor")
        if factor in seen_factors:
            continue
        pct = int(round(row["reduction_percent"]))
        if pct <= 0:
            continue
        seen_factors.add(factor)
        badges.append(f"{pct}% less CO₂ than {row['model']}")

    chart_bars: List[Dict[str, Any]] = [
        {
            "model": row["model"],
            "estimated_gco2e": row["estimated_gco2e"],
            "is_ours": False,
        }
        for row in comparison_models
    ]
    chart_bars.append(
        {
            "model": OUR_SYSTEM_NAME,
            "estimated_gco2e": _round1(actual),
            "is_ours": True,
        }
    )
    chart_bars.sort(key=lambda row: row["estimated_gco2e"], reverse=True)

    return {
        "comparison_models": comparison_models,
        "our_system": {
            "name": OUR_SYSTEM_NAME,
            "tagline": OUR_SYSTEM_TAGLINE,
            "carbon": _round1(actual),
        },
        "summary_cards": {
            "actual_emissions_gco2e": _round4(actual),
            "carbon_saved_gco2e": _round4(saved),
            "reduction_percent": _round1(efficiency),
            "heavy_model_baseline_gco2e": _round4(baseline),
        },
        "badges": badges,
        "chart_bars": chart_bars,
        "methodology": COMPARISON_METHODOLOGY,
        "breakdown": breakdown,
    }
