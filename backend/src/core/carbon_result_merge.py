"""
Carbon result field promotion & additive merges.

Keeps Summary Ready → Background → /job-result from inventing grid/region
zeros and from wiping routing / pipeline intelligence with empty overlays.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if value == "":
        return True
    if value == "unknown":
        return True
    return False


def _is_placeholder_number(value: Any) -> bool:
    """True when a numeric field is missing or a known unset placeholder."""
    if value is None:
        return True
    try:
        return float(value) == 0.0
    except (TypeError, ValueError):
        return False


def additive_dict_merge(
    base: Optional[Dict[str, Any]],
    overlay: Optional[Dict[str, Any]],
    *,
    overlay_wins_keys: Optional[set] = None,
) -> Dict[str, Any]:
    """
    Merge overlay into base without wiping populated sections.

    - Nested dicts merge recursively.
    - Overlay replaces base when base is empty/placeholder.
    - Keys in overlay_wins_keys always take overlay (finalize carbon metrics).
    - Never replace a non-empty dict/list with an empty one.
    """
    out: Dict[str, Any] = dict(base or {})
    overlay = overlay or {}
    wins = overlay_wins_keys or set()
    for key, value in overlay.items():
        if value is None:
            continue
        if isinstance(value, dict):
            existing = out.get(key)
            if isinstance(existing, dict):
                out[key] = additive_dict_merge(existing, value, overlay_wins_keys=wins)
            elif not existing:
                out[key] = dict(value)
            elif key in wins:
                out[key] = additive_dict_merge(existing if isinstance(existing, dict) else {}, value)
            continue
        if isinstance(value, list):
            existing = out.get(key)
            if key in wins or not existing:
                out[key] = list(value)
            continue
        if key in wins:
            out[key] = value
            continue
        cur = out.get(key)
        if _is_empty(cur) or (isinstance(value, (int, float)) and _is_placeholder_number(cur) and not _is_placeholder_number(value)):
            out[key] = value
    return out


def promote_carbon_from_region_decision(cd: Dict[str, Any]) -> Dict[str, Any]:
    """
    Lift real Electricity Maps / region scheduler values onto top-level carbon_data.

    Does not invent intensity or region names — only copies when present on
    region_decision (or nested grid legacy dict).
    """
    out = dict(cd or {})
    rd = out.get("region_decision") if isinstance(out.get("region_decision"), dict) else {}
    if not rd:
        return out
    grid = rd.get("grid") if isinstance(rd.get("grid"), dict) else {}

    intensity = rd.get("grid_carbon_intensity_gco2_kwh")
    if intensity is None:
        intensity = grid.get("intensity_gco2_kwh")
    if intensity is not None and (
        out.get("local_grid_gco2_kwh") is None
        or _is_placeholder_number(out.get("local_grid_gco2_kwh"))
    ):
        try:
            out["local_grid_gco2_kwh"] = float(intensity)
        except (TypeError, ValueError):
            pass

    zone = rd.get("grid_zone") or grid.get("zone")
    if zone and (_is_empty(out.get("grid_zone"))):
        out["grid_zone"] = str(zone)

    region_name = rd.get("selected_region_name")
    if region_name and (
        _is_empty(out.get("compute_location")) or out.get("compute_location") == "unknown"
    ):
        out["compute_location"] = str(region_name)
    elif zone and (_is_empty(out.get("compute_location")) or out.get("compute_location") == "unknown"):
        out["compute_location"] = str(zone)

    provider = rd.get("provider") or grid.get("provider") or grid.get("source")
    if provider and _is_empty(out.get("grid_source")):
        out["grid_source"] = str(provider)

    for src_key, dst_key in (
        ("datetime", "grid_datetime"),
        ("updated_at", "grid_updated_at"),
    ):
        raw = rd.get(dst_key) or grid.get(src_key)
        if raw and _is_empty(out.get(dst_key)):
            out[dst_key] = raw

    # Keep region_decision flat keys present for UI precedence
    if intensity is not None and rd.get("grid_carbon_intensity_gco2_kwh") is None:
        rd = dict(rd)
        try:
            rd["grid_carbon_intensity_gco2_kwh"] = float(intensity)
        except (TypeError, ValueError):
            pass
        out["region_decision"] = rd

    return out


# Authoritative keys from finalize / accounting — always win on background patch.
CARBON_FINALIZE_WIN_KEYS = {
    "carbon_saved_grams",
    "efficiency_percent",
    "baseline_cost_gco2e",
    "actual_cost_gco2e",
    "estimated_baseline_pipeline_emissions_g",
    "estimated_optimized_pipeline_emissions_g",
    "estimated_carbon_saved_g",
    "estimated_reduction_percent",
    "emissions_direction",
    "baseline_reference",
    "chunk_breakdown",
    "methodology",
    "assumptions_panel",
    "region_decision",
    "local_grid_gco2_kwh",
    "remote_grid_gco2_kwh",
    "compute_location",
    "baseline_energy_kwh",
    "actual_energy_kwh",
    "grid_zone",
    "grid_datetime",
    "grid_source",
    "grid_updated_at",
    "message",
    "total_chunks",
    "chunks_escalated",
    "breakdown",
    "routing_impact",
    "uncertainty",
    "input_tokens",
    "retrieved_context_tokens",
    "generated_tokens",
    "effective_tokens",
    "pue",
    "reporting_boundary",
    "reporting_boundary_label",
    "compile_calls",
    "compile_tokens",
    "compile_tier",
    "compile_carbon_g",
    "compile_substeps_ms",
}
