"""
Frontier-model comparison visualization (Boundary A).

Each frontier row estimates operational CO₂e if the *entire document workflow*
(same map + compile token mass + shared stages) were served by that single
model — identical workload to the naive heavy baseline, only J/token changes.

Our system bar uses the smart-routed ``actual_cost_gco2e``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from src.carbon import assumptions as A
from src.carbon.accounting import METHODOLOGY_TEXT as CARBON_METHODOLOGY
from src.carbon.energy_model import energy_to_co2e_g, joules_to_kwh

FRONTIER_MODEL_J_PER_TOKEN: Tuple[Tuple[str, float], ...] = (
    ("GPT-o3", 7.5),
    ("GPT-4", A.J_PER_TOKEN_TYPICAL["heavy"]),
    ("Llama 4 Behemoth", A.J_PER_TOKEN_TYPICAL["heavy"]),
    ("Claude 4 Opus", 6.0),
    ("GPT-4o", 4.0),
    ("Gemini 2.5 Pro", 3.8),
    ("Llama 4 Maverick", 2.8),
    ("Gemma 3", max(A.J_PER_TOKEN_TYPICAL["light"], 1.6)),
)

FRONTIER_RELATIVE_INTENSITY: Tuple[Tuple[str, float], ...] = tuple(
    (name, round(j / A.J_PER_TOKEN_TYPICAL["medium"], 4))
    for name, j in FRONTIER_MODEL_J_PER_TOKEN
)

OUR_SYSTEM_NAME = "Green Agentic Document Processing System"
OUR_SYSTEM_TAGLINE = "Smart Carbon-Aware Routing"

COMPARISON_METHODOLOGY = (
    "Each frontier bar answers: what if the ENTIRE document workflow "
    "(same map + compile token mass and shared parse/chunk/embed/retrieve stages) "
    "were processed by that single model? "
    "CO₂e = (shared_compute + (map+compile)×J_model) × PUE / 3.6e6 × Electricity Maps intensity. "
    "Our system bar is the carbon-aware per-chunk routed pipeline. "
    "Baseline reference = naive all-heavy frontier. "
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


def _workflow_inference_tokens(breakdown: Mapping[str, Any], data: Mapping[str, Any]) -> int:
    """Map + compile token mass — same workload as the naive frontier baseline."""
    map_total = int(_safe_float(breakdown.get("map_tokens_total")))
    if map_total <= 0:
        by_tier = breakdown.get("map_tokens_by_tier") or {}
        if isinstance(by_tier, dict):
            map_total = sum(int(_safe_float(v)) for v in by_tier.values())
    compile_tok = int(
        _safe_float(breakdown.get("compile_tokens") or data.get("compile_tokens"))
    )
    if map_total + compile_tok > 0:
        return map_total + compile_tok
    inp = int(_safe_float(breakdown.get("input_tokens") or data.get("input_tokens")))
    if inp > 0:
        return max(int(inp * 1.25), inp) + max(inp // 3, 0)
    return 0


def _estimate_frontier_gco2e(
    *,
    model_j_per_token: float,
    baseline_g: float,
    breakdown: Mapping[str, Any],
    data: Mapping[str, Any],
) -> float:
    intensity = _safe_float(data.get("local_grid_gco2_kwh"))
    if intensity <= 0:
        intensity = _safe_float(breakdown.get("grid_carbon_intensity_gco2_kwh"))
    if intensity <= 0 or baseline_g <= 0:
        return 0.0

    stages = breakdown.get("baseline_stages_gco2e")
    if not isinstance(stages, dict):
        stages = {}

    inference_g = _safe_float(stages.get("inference_gco2e"))
    other_g = 0.0
    for key, val in stages.items():
        if key in ("inference_gco2e", "total_gco2e", "infrastructure_gco2e"):
            continue
        other_g += _safe_float(val)
    infra_g = _safe_float(stages.get("infrastructure_gco2e"))

    if inference_g <= 0:
        inference_g = baseline_g * 0.86
        other_g = baseline_g * 0.05
        infra_g = max(0.0, baseline_g - inference_g - other_g)

    token_mass = _workflow_inference_tokens(breakdown, data)
    if token_mass <= 0:
        heavy_j = A.J_PER_TOKEN_TYPICAL["heavy"]
        ratio = float(model_j_per_token) / heavy_j if heavy_j > 0 else 1.0
        new_inference = inference_g * ratio
        it_new = other_g + new_inference
        it_old = other_g + inference_g
        infra_new = infra_g * (it_new / it_old) if it_old > 0 else infra_g
        return max(0.0, it_new + infra_new)

    inference_j = float(token_mass) * float(model_j_per_token)
    # Match stage attribution: IT grams without PUE; infrastructure carries (PUE−1).
    new_inference_g = energy_to_co2e_g(joules_to_kwh(inference_j), intensity)

    it_old = other_g + inference_g
    it_new = other_g + new_inference_g
    infra_new = infra_g * (it_new / it_old) if it_old > 0 else infra_g
    return max(0.0, it_new + infra_new)


def build_frontier_comparison(
    carbon_data: Optional[Mapping[str, Any]],
    *,
    model_factors: Optional[Sequence[Tuple[str, float]]] = None,
    badge_top_n: int = BADGE_TOP_N,
) -> Dict[str, Any]:
    data = dict(carbon_data or {})
    baseline = _resolve_baseline_co2(data)
    actual = _safe_float(data.get("actual_cost_gco2e"))
    breakdown = data.get("breakdown") if isinstance(data.get("breakdown"), dict) else {}
    if actual <= 0:
        actual = _safe_float(breakdown.get("actual_co2e_g"))
    if "carbon_saved_grams" in data:
        saved = _safe_float(data.get("carbon_saved_grams"))
    else:
        saved = baseline - actual if baseline > 0 else 0.0
    if "efficiency_percent" in data:
        efficiency = _safe_float(data.get("efficiency_percent"))
    elif baseline > 0:
        efficiency = (saved / baseline) * 100.0
    else:
        efficiency = 0.0

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

    if model_factors is not None:
        medium_j = A.J_PER_TOKEN_TYPICAL["medium"]
        models: List[Tuple[str, float]] = [
            (name, float(factor) * medium_j) for name, factor in model_factors
        ]
    else:
        models = list(FRONTIER_MODEL_J_PER_TOKEN)

    comparison_models: List[Dict[str, Any]] = []
    medium_j = A.J_PER_TOKEN_TYPICAL["medium"]

    for model_name, model_j in models:
        estimated = _estimate_frontier_gco2e(
            model_j_per_token=float(model_j),
            baseline_g=baseline,
            breakdown=breakdown,
            data=data,
        )
        saved_g = estimated - actual
        reduction = (saved_g / estimated) * 100.0 if estimated > 0 else 0.0
        comparison_models.append(
            {
                "model": model_name,
                "relative_factor": round(float(model_j) / medium_j, 4) if medium_j else 1.0,
                "j_per_token": float(model_j),
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
            "estimated_optimized_pipeline_emissions_g": _round4(actual),
            "estimated_baseline_pipeline_emissions_g": _round4(baseline),
            "emissions_direction": data.get("emissions_direction")
            or breakdown.get("emissions_direction"),
            "reporting_boundary_label": data.get("reporting_boundary_label")
            or "Operational Emissions (Boundary A)",
        },
        "badges": badges,
        "chart_bars": chart_bars,
        "methodology": COMPARISON_METHODOLOGY,
        "breakdown": breakdown,
        "chunk_breakdown": data.get("chunk_breakdown")
        or breakdown.get("chunk_breakdown")
        or [],
    }
