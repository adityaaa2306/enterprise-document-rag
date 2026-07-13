"""
Reusable workflow carbon accounting service.

Every report / dashboard / API carbon field must come from
``estimate_workflow_carbon`` so methodologies cannot diverge.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional

from src.carbon.electricity_maps import fetch_grid_carbon_intensity
from src.carbon.energy_model import (
    BASELINE_RETRIEVED_CHUNK_CAP,
    GPT4O_MINI_MEDIUM_WH,
    GPT4O_MINI_REF_TOKENS,
    baseline_retrieved_tokens,
    chars_to_tokens,
    energy_to_co2e_g,
    estimate_baseline_energy_wh,
    estimate_green_energy_wh,
    estimate_tokens,
    wh_to_kwh,
)

log = logging.getLogger(__name__)

METHODOLOGY_TEXT = (
    "This estimate is based on workflow-level AI energy estimation and real-time "
    "electricity carbon intensity. Energy consumption is estimated from the AI "
    "workflow (embedding, retrieval, routing, inference and generation). "
    "Carbon emissions are calculated as CO₂e = Energy × Grid Carbon Intensity "
    "using live Electricity Maps data. "
    f"Inference energy is calibrated to GPT-4o mini medium-query measurements "
    f"({GPT4O_MINI_MEDIUM_WH:g} Wh ≈ {GPT4O_MINI_REF_TOKENS} tokens; arXiv:2505.09598). "
    "Baseline assumes a conventional single-model pipeline with serving/PUE overhead; "
    "the green pipeline only charges models and stages actually invoked."
)


def _chunk_text_stats(chunks: Any) -> Dict[str, int]:
    texts = []
    if isinstance(chunks, list):
        for c in chunks:
            if hasattr(c, "content"):
                texts.append(getattr(c, "content", "") or "")
            elif isinstance(c, dict):
                texts.append(str(c.get("content") or c.get("text") or ""))
            else:
                texts.append(str(c))
    joined = "\n".join(texts)
    input_tokens = estimate_tokens(joined)
    n = max(0, len(texts))
    avg = (input_tokens // n) if n else 0
    return {"input_tokens": input_tokens, "total_chunks": n, "avg_chunk_tokens": avg}


def _map_tokens_by_tier(state: Mapping[str, Any], *, input_tokens: int, map_tier: str) -> Dict[str, int]:
    """
    Attribute map-summarize work by tier.

    Prefer model_usage_chars when present, but cap at ~2× document tokens so
    hierarchical compile bookkeeping cannot inflate map energy.
    """
    usage = state.get("model_usage_chars") or {}
    cap = max(input_tokens * 2, input_tokens + 500)
    # Map stage only — orchestrator "large" chars are hierarchical compile
    # prompts and are accounted via compile_tokens, not here.
    out = {
        "light": min(chars_to_tokens(int(usage.get("light") or 0)), cap),
        "medium": min(chars_to_tokens(int(usage.get("medium") or 0)), cap),
        "heavy": min(chars_to_tokens(int(usage.get("heavy") or 0)), cap),
    }
    if sum(out.values()) <= 0 and input_tokens > 0:
        key = map_tier if map_tier in out else "medium"
        # One pass over the document at the selected map tier (+ short outputs)
        out[key] = min(cap, int(input_tokens * 1.25))
    return out


def estimate_workflow_carbon(
    job_id: str,
    state: Mapping[str, Any],
    *,
    grid: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Estimate energy for baseline vs green pipelines, then convert to CO₂e
    with Electricity Maps intensity.

    Returns a dict compatible with legacy carbon_data fields plus a full
    ``breakdown`` for transparent dashboards.
    """
    import math

    chunks = state.get("chunks") or []
    stats = _chunk_text_stats(chunks)
    input_tokens = int(stats["input_tokens"])
    total_chunks = int(state.get("total_chunks") or stats["total_chunks"] or 0)
    avg_chunk = int(stats["avg_chunk_tokens"] or 0)
    if total_chunks <= 0:
        total_chunks = max(1, stats["total_chunks"] or 1)

    final_summary = str(state.get("final_summary") or "")
    generated_tokens = estimate_tokens(final_summary)

    usage = state.get("model_usage_chars") or {}
    # Map-stage output estimate (summaries are shorter than inputs)
    map_out_est = max(generated_tokens, min(input_tokens // 3, chars_to_tokens(int(usage.get("medium") or 0) + int(usage.get("light") or 0)) // 2))
    if map_out_est > generated_tokens:
        generated_tokens = max(generated_tokens, min(map_out_est, input_tokens // 2))

    retrieved_context_tokens = baseline_retrieved_tokens(
        input_tokens, total_chunks, avg_chunk or 350
    )
    retrieved_context_tokens = min(
        retrieved_context_tokens,
        BASELINE_RETRIEVED_CHUNK_CAP * max(avg_chunk or 350, 200),
    )

    effective_tokens = input_tokens + retrieved_context_tokens + generated_tokens

    decision = state.get("routing_decision") or {}
    map_tier = str(decision.get("tier") or "medium")
    compile_tier = str(decision.get("compile_tier") or "heavy")
    chunks_escalated = int(state.get("chunks_escalated") or 0)

    map_by_tier = _map_tokens_by_tier(state, input_tokens=input_tokens, map_tier=map_tier)

    # Escalation: re-summarize only escalated fraction at the higher tier
    if chunks_escalated > 0 and total_chunks > 0:
        frac = min(1.0, float(chunks_escalated) / float(total_chunks))
        esc_tokens = int(input_tokens * frac * 1.25)
        esc_key = "heavy" if compile_tier in ("heavy", "large") else (compile_tier or "heavy")
        if esc_key not in map_by_tier:
            esc_key = "heavy"
        map_by_tier[esc_key] = map_by_tier.get(esc_key, 0) + esc_tokens

    # Hierarchical compile: ~ceil(log_batch(n)) passes over summary-sized text —
    # NOT the inflated model_usage_chars["large"] from prompt concatenation.
    summary_tokens = max(generated_tokens, min(input_tokens // 3, 6000))
    batch_size = 8
    n_rounds = max(1, int(math.ceil(math.log(max(total_chunks, 2), batch_size))))
    compile_tokens = int(summary_tokens * n_rounds)

    verification_tokens = total_chunks * 40

    baseline = estimate_baseline_energy_wh(
        input_tokens=input_tokens,
        retrieved_context_tokens=retrieved_context_tokens,
        generated_tokens=generated_tokens,
    )
    green = estimate_green_energy_wh(
        input_tokens=input_tokens,
        retrieved_context_tokens=retrieved_context_tokens,
        generated_tokens=generated_tokens,
        map_tokens_by_tier=map_by_tier,
        compile_tokens=compile_tokens,
        compile_tier=compile_tier,
        chunks_escalated=chunks_escalated,
        verification_tokens=verification_tokens,
    )

    grid_info = dict(grid) if grid is not None else fetch_grid_carbon_intensity()
    intensity = float(grid_info.get("intensity_gco2_kwh") or 0.0)

    baseline_kwh = wh_to_kwh(baseline["total_wh"])
    actual_kwh = wh_to_kwh(green["total_wh"])

    # Guard: optimized path should not exceed conventional single-pass baseline energy.
    # If routing chose a heavier tier than the baseline calibration model, still report
    # honestly but never invent savings.
    baseline_co2 = energy_to_co2e_g(baseline_kwh, intensity)
    actual_co2 = energy_to_co2e_g(actual_kwh, intensity)
    saved = max(0.0, baseline_co2 - actual_co2)
    if baseline_co2 > 0:
        efficiency = min(100.0, (saved / baseline_co2) * 100.0)
    else:
        efficiency = 0.0
    efficiency = round(efficiency, 1)

    message = (
        f"Saved {saved:.2f}g CO₂e ({efficiency:.1f}% reduction) — "
        f"energy {actual_kwh:.4f} vs baseline {baseline_kwh:.4f} kWh "
        f"@ {intensity:.0f} gCO₂e/kWh ({grid_info.get('zone')})."
    )
    log.info("Job %s: %s", job_id, message)

    breakdown = {
        "input_tokens": input_tokens,
        "retrieved_context_tokens": retrieved_context_tokens,
        "generated_tokens": generated_tokens,
        "effective_tokens": int(effective_tokens),
        "baseline_energy_kwh": round(baseline_kwh, 6),
        "optimized_energy_kwh": round(actual_kwh, 6),
        "baseline_energy_wh": round(float(baseline["total_wh"]), 4),
        "optimized_energy_wh": round(float(green["total_wh"]), 4),
        "grid_carbon_intensity_gco2_kwh": round(intensity, 2),
        "grid_zone": grid_info.get("zone"),
        "grid_datetime": grid_info.get("datetime"),
        "grid_updated_at": grid_info.get("updated_at"),
        "grid_source": grid_info.get("source"),
        "baseline_co2e_g": round(baseline_co2, 4),
        "actual_co2e_g": round(actual_co2, 4),
        "carbon_saved_g": round(saved, 4),
        "reduction_percent": efficiency,
        "baseline_stages_wh": {
            k: round(float(v), 4)
            for k, v in baseline.items()
            if k.endswith("_wh")
        },
        "optimized_stages_wh": {
            k: round(float(v), 4)
            for k, v in green.items()
            if k.endswith("_wh")
        },
        "map_tokens_by_tier": dict(map_by_tier),
        "compile_tokens": compile_tokens,
        "map_tier": map_tier,
        "compile_tier": compile_tier,
        "retrieved_chunk_cap": BASELINE_RETRIEVED_CHUNK_CAP,
        "calibration": {
            "reference": "GPT-4o mini medium query",
            "reference_wh": GPT4O_MINI_MEDIUM_WH,
            "reference_tokens": GPT4O_MINI_REF_TOKENS,
            "citation": "arXiv:2505.09598",
        },
    }

    return {
        "carbon_saved_grams": float(saved),
        "baseline_cost_gco2e": float(baseline_co2),
        "actual_cost_gco2e": float(actual_co2),
        "efficiency_percent": float(efficiency),
        "message": message,
        "local_grid_gco2_kwh": float(intensity),
        "remote_grid_gco2_kwh": None,
        "compute_location": str(grid_info.get("zone") or "unknown"),
        "total_chunks": int(total_chunks),
        "chunks_escalated": int(chunks_escalated),
        "baseline_energy_kwh": float(baseline_kwh),
        "actual_energy_kwh": float(actual_kwh),
        "grid_zone": grid_info.get("zone"),
        "grid_datetime": grid_info.get("datetime"),
        "grid_source": grid_info.get("source"),
        "breakdown": breakdown,
        "methodology": METHODOLOGY_TEXT,
    }
