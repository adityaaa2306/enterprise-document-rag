"""
Reusable operational carbon accounting (Boundary A).

Every report / dashboard / API carbon field must come from
``estimate_workflow_carbon`` so methodologies cannot diverge.

Equation
--------
    E_compute (J)  = Σ stage tokens × J/token
    E_facility (J) = E_compute × PUE × INFRASTRUCTURE_FACTOR
    E (kWh)        = E_facility / 3_600_000
    CO₂e (g)       = E (kWh) × Electricity Maps intensity (gCO₂e/kWh)

Baseline
--------
Naive conventional pipeline: ONE frontier (heavy) model for all map + compile
inference. No CRE / light / medium routing.

Optimized
---------
Actual carbon-aware routing: map emissions from per-chunk light/medium/heavy
tiers (``chunk_routing``), compile at the selected compile tier.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Mapping, Optional, Tuple

from src.carbon import assumptions as A
from src.carbon.energy_model import (
    BASELINE_RETRIEVED_CHUNK_CAP,
    GPT4O_MINI_MEDIUM_WH,
    GPT4O_MINI_REF_TOKENS,
    apply_facility_overhead,
    baseline_retrieved_tokens,
    chars_to_tokens,
    energy_to_co2e_g,
    estimate_baseline_energy,
    estimate_green_energy,
    estimate_tokens,
    inference_joules,
    joules_to_kwh,
)

log = logging.getLogger(__name__)

METHODOLOGY_TEXT = (
    "This system estimates operational carbon emissions (Reporting Boundary A) using "
    "energy-per-token estimates, live regional electricity carbon intensity from "
    "Electricity Maps, and datacenter Power Usage Effectiveness (PUE). "
    f"Facility energy = compute joules × PUE ({A.PUE}) × infrastructure factor "
    f"({A.INFRASTRUCTURE_FACTOR}). "
    f"Medium-tier inference is anchored to GPT-4o mini measurements "
    f"({GPT4O_MINI_MEDIUM_WH:g} Wh ≈ {GPT4O_MINI_REF_TOKENS} tokens; arXiv:2505.09598) "
    f"≈ {A.GPT4O_MINI_J_PER_TOKEN_TYPICAL:.3f} J/token. "
    "Baseline = naive single-frontier (heavy) model for all map + compile inference "
    "(no smart routing). Optimized = actual per-chunk Light/Medium/Heavy routing "
    "plus selected compile tier. Shared stages (parse/chunk/embed/retrieve/verify) "
    "are identical. Excluded: model training, hardware manufacturing, end-of-life. "
    "Values are estimates — providers do not expose metered per-request facility energy."
)

ASSUMPTIONS_PANEL_TEXT = (
    "Carbon Calculation Methodology (Boundary A — Operational)\n"
    "=========================================================\n\n"
    "Equation:\n"
    "  CO₂e(g) = (Σ tokens × J/token × PUE × INFRASTRUCTURE_FACTOR / 3_600_000)\n"
    "            × grid_intensity (gCO₂e/kWh)\n\n"
    "Baseline (naive conventional pipeline):\n"
    "  • Same document, same token mass, same shared stages\n"
    "  • ALL map + compile inference charged at the frontier/heavy J/token\n"
    "  • NO CRE, NO light/medium routing, NO complexity-based demotion\n\n"
    "Optimized (carbon-aware routing):\n"
    "  • Same shared stages (parse, chunk, embed, retrieve, verify)\n"
    "  • Map emissions = Σ over chunks (chunk_tokens × J/token of routed tier)\n"
    "  • Compile at the selected compile tier (medium or heavy)\n"
    "  • Includes a small CRE/routing orchestration stub\n\n"
    f"PUE = {A.PUE}  |  Infrastructure factor = {A.INFRASTRUCTURE_FACTOR}\n"
    f"J/token typical: light={A.J_PER_TOKEN_TYPICAL['light']}, "
    f"medium={A.J_PER_TOKEN_TYPICAL['medium']:.4f}, "
    f"heavy={A.J_PER_TOKEN_TYPICAL['heavy']}\n"
    "Grid intensity: Electricity Maps (live) with local fallback.\n\n"
    "Excluded: training emissions, hardware manufacturing, end-of-life LCA.\n"
    "These are estimates suitable for comparative evaluation, not metered facility joules."
)


def _resolve_baseline_j_per_token() -> Tuple[str, float]:
    """Return (reference_key, J/token) for the naive frontier baseline."""
    try:
        from src.core.config import settings

        key = str(
            getattr(settings, "CARBON_BASELINE_REFERENCE", None)
            or A.DEFAULT_BASELINE_REFERENCE
        ).strip().lower()
    except Exception:
        key = A.DEFAULT_BASELINE_REFERENCE
    table = A.BASELINE_REFERENCE_J_PER_TOKEN
    if key not in table:
        key = "heavy"
    return key, float(table[key])


def _chunk_text(chunk: Any) -> str:
    if hasattr(chunk, "content"):
        return getattr(chunk, "content", "") or ""
    if isinstance(chunk, dict):
        return str(chunk.get("content") or chunk.get("text") or "")
    return str(chunk or "")


def _chunk_text_stats(chunks: Any) -> Dict[str, int]:
    texts = []
    if isinstance(chunks, list):
        for c in chunks:
            texts.append(_chunk_text(c))
    joined = "\n".join(texts)
    input_tokens = estimate_tokens(joined)
    n = max(0, len(texts))
    avg = (input_tokens // n) if n else 0
    return {"input_tokens": input_tokens, "total_chunks": n, "avg_chunk_tokens": avg}


def _final_tier_by_chunk(state: Mapping[str, Any]) -> Dict[int, str]:
    """Prefer post-escalation tier from telemetry, else chunk_routing."""
    final: Dict[int, str] = {}
    for row in state.get("chunk_routing") or []:
        if not isinstance(row, dict):
            continue
        try:
            idx = int(row.get("chunk_index", -1))
        except (TypeError, ValueError):
            continue
        if idx < 0:
            continue
        tier = str(row.get("tier") or "medium").lower()
        if tier == "large":
            tier = "heavy"
        if tier not in ("light", "medium", "heavy"):
            tier = "medium"
        final[idx] = tier

    for t in state.get("agent_telemetry") or []:
        if not isinstance(t, dict):
            continue
        phase = str(t.get("phase") or "")
        if phase not in ("map", "escalate"):
            continue
        try:
            idx = int(t.get("chunk_index"))
        except (TypeError, ValueError):
            continue
        tier = str(t.get("tier") or "").lower()
        if tier == "large":
            tier = "heavy"
        if tier in ("light", "medium", "heavy"):
            final[idx] = tier
    return final


def _model_for_chunk(idx: int, tier: str, state: Mapping[str, Any]) -> str:
    for row in state.get("chunk_routing") or []:
        if not isinstance(row, dict):
            continue
        try:
            if int(row.get("chunk_index", -1)) == idx and row.get("model"):
                return str(row.get("model"))
        except (TypeError, ValueError):
            continue
    for t in reversed(list(state.get("agent_telemetry") or [])):
        if not isinstance(t, dict):
            continue
        try:
            if int(t.get("chunk_index", -1)) != idx:
                continue
        except (TypeError, ValueError):
            continue
        if t.get("model_id") or t.get("model"):
            return str(t.get("model_id") or t.get("model"))
    decision = state.get("routing_decision") or {}
    if tier == str(decision.get("tier") or "") and decision.get("selected_model"):
        return str(decision["selected_model"])
    return f"{tier}-tier"


def _chunk_map_attribution(
    state: Mapping[str, Any],
    *,
    input_tokens: int,
    intensity: float,
    j_per_token: Optional[Mapping[str, float]] = None,
) -> Tuple[Dict[str, int], List[Dict[str, Any]]]:
    """
    Distribute structural map token mass across chunks by text weight and
    charge each chunk at its routed tier.
    """
    chunks = list(state.get("chunks") or [])
    n = len(chunks)
    map_tokens_total = (
        max(int(input_tokens * 1.25), input_tokens) if input_tokens > 0 else 0
    )
    map_by_tier: Dict[str, int] = {"light": 0, "medium": 0, "heavy": 0}
    rows: List[Dict[str, Any]] = []

    decision = state.get("routing_decision") or {}
    default_tier = str(decision.get("tier") or "medium").lower()
    if default_tier == "large":
        default_tier = "heavy"
    if default_tier not in map_by_tier:
        default_tier = "medium"

    final_tiers = _final_tier_by_chunk(state)
    table = j_per_token or A.J_PER_TOKEN_TYPICAL

    if n == 0:
        map_by_tier[default_tier] = map_tokens_total
        return map_by_tier, rows

    weights = [max(1, estimate_tokens(_chunk_text(c))) for c in chunks]
    weight_sum = float(sum(weights)) or 1.0

    allocated = 0
    for i, w in enumerate(weights):
        if i == n - 1:
            share = max(0, map_tokens_total - allocated)
        else:
            share = int(round(map_tokens_total * (w / weight_sum)))
            allocated += share

        tier = final_tiers.get(i, default_tier)
        if tier not in map_by_tier:
            tier = default_tier
        map_by_tier[tier] = int(map_by_tier.get(tier) or 0) + share

        joules = inference_joules(share, tier=tier, j_per_token=table)
        facility_j = apply_facility_overhead(joules)
        energy_kwh = joules_to_kwh(facility_j)
        co2 = energy_to_co2e_g(energy_kwh, intensity)
        model = _model_for_chunk(i, tier, state)
        rows.append(
            {
                "chunk_index": i,
                "tier": tier,
                "model": model,
                "input_tokens": int(w),
                "map_tokens": int(share),
                "energy_kwh": round(energy_kwh, 8),
                "energy_joules": round(facility_j, 4),
                "co2e_g": round(co2, 6),
                "j_per_token": float(table.get(tier, table.get("medium", 2.55))),
            }
        )

    return map_by_tier, rows


def _energy_pack_to_stage_co2(
    pack: Mapping[str, float], intensity: float
) -> Dict[str, float]:
    it_keys = (
        ("parsing_gco2e", "parsing_j"),
        ("chunking_gco2e", "chunking_j"),
        ("embedding_gco2e", "embedding_j"),
        ("retrieval_gco2e", "retrieval_j"),
        ("routing_gco2e", "routing_j"),
        ("inference_gco2e", "inference_j"),
        ("verification_gco2e", "verification_j"),
    )
    clean: Dict[str, float] = {}
    compute_j = 0.0
    for label, jk in it_keys:
        j = float(pack.get(jk) or 0.0)
        compute_j += j
        clean[label] = round(energy_to_co2e_g(joules_to_kwh(j), intensity), 4)

    infra_j = compute_j * max(0.0, float(A.PUE) - 1.0) * float(A.INFRASTRUCTURE_FACTOR)
    clean["infrastructure_gco2e"] = round(
        energy_to_co2e_g(joules_to_kwh(infra_j), intensity), 4
    )
    clean["total_gco2e"] = round(sum(clean.values()), 4)
    return clean


def _routing_impact(
    *,
    total_chunks: int,
    map_tier: str,
    compile_tier: str,
    chunks_escalated: int,
    compile_calls: int,
    map_tokens_by_tier: Mapping[str, int],
    chunk_breakdown: List[Dict[str, Any]],
    baseline_kwh: float,
    actual_kwh: float,
    intensity: float,
) -> Dict[str, Any]:
    if chunk_breakdown:
        light = sum(1 for r in chunk_breakdown if r.get("tier") == "light")
        medium = sum(1 for r in chunk_breakdown if r.get("tier") == "medium")
        heavy = sum(1 for r in chunk_breakdown if r.get("tier") == "heavy")
    else:
        tier = (map_tier or "medium").lower()
        light = medium = heavy = 0
        if total_chunks > 0:
            if tier == "light":
                light = max(0, total_chunks - chunks_escalated)
                heavy = chunks_escalated
            elif tier in ("heavy", "large"):
                heavy = total_chunks
            else:
                medium = max(0, total_chunks - chunks_escalated)
                heavy = chunks_escalated

    map_tokens = sum(int(v or 0) for v in (map_tokens_by_tier or {}).values())
    hypo_map_j = inference_joules(map_tokens, tier="heavy")
    actual_map_j = sum(
        inference_joules(int(tok or 0), tier=str(t))
        for t, tok in (map_tokens_by_tier or {}).items()
    )
    routing_map_savings_j = max(0.0, hypo_map_j - actual_map_j)
    routing_map_savings_kwh = joules_to_kwh(apply_facility_overhead(routing_map_savings_j))
    routing_map_savings_g = energy_to_co2e_g(routing_map_savings_kwh, intensity)
    pipeline_kwh_delta = baseline_kwh - actual_kwh

    return {
        "total_chunks": int(total_chunks),
        "light_chunks": int(max(0, light)),
        "medium_chunks": int(max(0, medium)),
        "heavy_chunks": int(max(0, heavy)),
        "escalated_chunks": int(max(0, chunks_escalated)),
        "compile_calls": int(max(0, compile_calls)),
        "map_tier": map_tier,
        "compile_tier": compile_tier,
        "energy_vs_all_heavy_map_kwh_saved": round(routing_map_savings_kwh, 6),
        "co2e_vs_all_heavy_map_g_saved": round(routing_map_savings_g, 4),
        "pipeline_energy_kwh_saved_vs_baseline": round(pipeline_kwh_delta, 6),
        "pipeline_co2e_g_saved_vs_baseline": round(
            energy_to_co2e_g(pipeline_kwh_delta, intensity), 4
        ),
        "model_distribution": {
            "light": int(max(0, light)),
            "medium": int(max(0, medium)),
            "heavy": int(max(0, heavy)),
        },
    }


def _uncertainty_band(
    *,
    input_tokens: int,
    retrieved_context_tokens: int,
    generated_tokens: int,
    map_by_tier: Mapping[str, int],
    compile_tokens: int,
    compile_tier: str,
    chunks_escalated: int,
    verification_tokens: int,
    map_tokens_total: int,
    baseline_j_per_token: float,
    intensity: float,
) -> Dict[str, Any]:
    if not A.ENABLE_UNCERTAINTY_BANDS:
        return {"enabled": False}

    bands: Dict[str, Dict[str, float]] = {}
    for name in ("low", "typical", "high"):
        table = A.j_per_token_table(name)
        heavy_typ = A.J_PER_TOKEN_TYPICAL["heavy"]
        heavy_band = float(table.get("heavy") or heavy_typ)
        scale = heavy_band / heavy_typ if heavy_typ > 0 else 1.0
        base_j = baseline_j_per_token * scale
        base = estimate_baseline_energy(
            input_tokens=input_tokens,
            retrieved_context_tokens=retrieved_context_tokens,
            generated_tokens=generated_tokens,
            map_tokens=map_tokens_total,
            compile_tokens=compile_tokens,
            verification_tokens=verification_tokens,
            baseline_j_per_token=base_j,
        )
        green = estimate_green_energy(
            input_tokens=input_tokens,
            retrieved_context_tokens=retrieved_context_tokens,
            generated_tokens=generated_tokens,
            map_tokens_by_tier=map_by_tier,
            compile_tokens=compile_tokens,
            compile_tier=compile_tier,
            chunks_escalated=chunks_escalated,
            verification_tokens=verification_tokens,
            j_per_token=table,
        )
        bands[name] = {
            "baseline_energy_kwh": round(float(base["total_kwh"]), 6),
            "optimized_energy_kwh": round(float(green["total_kwh"]), 6),
            "baseline_co2e_g": round(
                energy_to_co2e_g(float(base["total_kwh"]), intensity), 4
            ),
            "optimized_co2e_g": round(
                energy_to_co2e_g(float(green["total_kwh"]), intensity), 4
            ),
        }

    return {
        "enabled": True,
        "baseline": {
            "low_gco2e": bands["low"]["baseline_co2e_g"],
            "typical_gco2e": bands["typical"]["baseline_co2e_g"],
            "high_gco2e": bands["high"]["baseline_co2e_g"],
        },
        "optimized": {
            "low_gco2e": bands["low"]["optimized_co2e_g"],
            "typical_gco2e": bands["typical"]["optimized_co2e_g"],
            "high_gco2e": bands["high"]["optimized_co2e_g"],
        },
        "bands": bands,
    }


def estimate_workflow_carbon(
    job_id: str,
    state: Mapping[str, Any],
    *,
    grid: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
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
    map_out_est = max(
        generated_tokens,
        min(
            input_tokens // 3,
            chars_to_tokens(
                int(usage.get("medium") or 0) + int(usage.get("light") or 0)
            )
            // 2,
        ),
    )
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
    compile_meta = state.get("compile_meta") or {}
    if compile_meta.get("used_heavy"):
        compile_tier = "heavy"
    chunks_escalated = int(state.get("chunks_escalated") or 0)

    summary_tokens = max(generated_tokens, min(input_tokens // 3, 6000))
    batch_size = 8
    n_rounds = max(1, int(math.ceil(math.log(max(total_chunks, 2), batch_size))))
    compile_calls = max(
        1, int(math.ceil(total_chunks / float(batch_size))) + (n_rounds - 1)
    )
    compile_tokens = int(summary_tokens * n_rounds)
    verification_tokens = total_chunks * 40
    map_tokens_total = (
        max(int(input_tokens * 1.25), input_tokens) if input_tokens > 0 else 0
    )

    grid_info = dict(grid) if grid is not None else None
    region_decision_dict: Optional[Dict[str, Any]] = None
    if grid_info is None:
        # Grid intensity ALWAYS flows through the Region Scheduler → Carbon Provider.
        # Accounting never calls Electricity Maps directly.
        from src.carbon.scheduler import estimate_workload_from_state, schedule_region

        decision = schedule_region(estimate_workload_from_state(state))
        region_decision_dict = decision.to_dict()
        grid_info = decision.grid.to_legacy_dict()
    intensity = float(grid_info.get("intensity_gco2_kwh") or 0.0)

    baseline_ref, baseline_j = _resolve_baseline_j_per_token()
    map_by_tier, chunk_breakdown = _chunk_map_attribution(
        state, input_tokens=input_tokens, intensity=intensity
    )

    baseline = estimate_baseline_energy(
        input_tokens=input_tokens,
        retrieved_context_tokens=retrieved_context_tokens,
        generated_tokens=generated_tokens,
        map_tokens=map_tokens_total,
        compile_tokens=compile_tokens,
        verification_tokens=verification_tokens,
        baseline_j_per_token=baseline_j,
    )
    green = estimate_green_energy(
        input_tokens=input_tokens,
        retrieved_context_tokens=retrieved_context_tokens,
        generated_tokens=generated_tokens,
        map_tokens_by_tier=map_by_tier,
        compile_tokens=compile_tokens,
        compile_tier=compile_tier,
        chunks_escalated=chunks_escalated,
        verification_tokens=verification_tokens,
    )

    baseline_kwh = float(baseline["total_kwh"])
    actual_kwh = float(green["total_kwh"])

    baseline_co2 = energy_to_co2e_g(baseline_kwh, intensity)
    actual_co2 = energy_to_co2e_g(actual_kwh, intensity)
    saved = baseline_co2 - actual_co2  # signed; negative = increased emissions
    if baseline_co2 > 0:
        efficiency = (saved / baseline_co2) * 100.0
    else:
        efficiency = 0.0
    efficiency = round(efficiency, 1)

    baseline_stages = _energy_pack_to_stage_co2(baseline, intensity)
    optimized_stages = _energy_pack_to_stage_co2(green, intensity)

    chunk_map_co2_sum = sum(float(r.get("co2e_g") or 0.0) for r in chunk_breakdown)
    map_j = float(green.get("map_inference_j") or 0.0)
    map_facility_co2 = energy_to_co2e_g(
        joules_to_kwh(apply_facility_overhead(map_j)), intensity
    )

    routing = _routing_impact(
        total_chunks=total_chunks,
        map_tier=map_tier,
        compile_tier=compile_tier,
        chunks_escalated=chunks_escalated,
        compile_calls=compile_calls,
        map_tokens_by_tier=map_by_tier,
        chunk_breakdown=chunk_breakdown,
        baseline_kwh=baseline_kwh,
        actual_kwh=actual_kwh,
        intensity=intensity,
    )

    uncertainty = _uncertainty_band(
        input_tokens=input_tokens,
        retrieved_context_tokens=retrieved_context_tokens,
        generated_tokens=generated_tokens,
        map_by_tier=map_by_tier,
        compile_tokens=compile_tokens,
        compile_tier=compile_tier,
        chunks_escalated=chunks_escalated,
        verification_tokens=verification_tokens,
        map_tokens_total=map_tokens_total,
        baseline_j_per_token=baseline_j,
        intensity=intensity,
    )

    snap = A.assumption_snapshot()
    emissions_direction = (
        "reduced"
        if saved > 1e-9
        else ("increased" if saved < -1e-9 else "unchanged")
    )

    message = (
        f"Estimated operational {'savings' if saved >= 0 else 'increase'} "
        f"{abs(saved):.2f}g CO₂e ({efficiency:+.1f}% vs naive frontier baseline) — "
        f"energy {actual_kwh:.4f} vs baseline {baseline_kwh:.4f} kWh "
        f"@ {intensity:.0f} gCO₂e/kWh ({grid_info.get('zone')}) "
        f"[Boundary A, PUE={A.PUE}, baseline_ref={baseline_ref}]."
    )
    log.info("Job %s: %s", job_id, message)

    breakdown = {
        "input_tokens": input_tokens,
        "retrieved_context_tokens": retrieved_context_tokens,
        "generated_tokens": generated_tokens,
        "effective_tokens": int(effective_tokens),
        "baseline_energy_kwh": round(baseline_kwh, 6),
        "optimized_energy_kwh": round(actual_kwh, 6),
        "baseline_energy_wh": round(baseline_kwh * 1000.0, 4),
        "optimized_energy_wh": round(actual_kwh * 1000.0, 4),
        "grid_carbon_intensity_gco2_kwh": round(intensity, 2),
        "grid_zone": grid_info.get("zone"),
        "grid_datetime": grid_info.get("datetime"),
        "grid_updated_at": grid_info.get("updated_at"),
        "grid_source": grid_info.get("source"),
        "baseline_co2e_g": round(baseline_co2, 4),
        "actual_co2e_g": round(actual_co2, 4),
        "carbon_saved_g": round(saved, 4),
        "reduction_percent": efficiency,
        "emissions_direction": emissions_direction,
        "estimated_baseline_pipeline_emissions_g": round(baseline_co2, 4),
        "estimated_optimized_pipeline_emissions_g": round(actual_co2, 4),
        "reporting_boundary": snap.reporting_boundary,
        "reporting_boundary_label": "Operational Emissions (Boundary A)",
        "pue": A.PUE,
        "infrastructure_factor": A.INFRASTRUCTURE_FACTOR,
        "baseline_stages_gco2e": baseline_stages,
        "optimized_stages_gco2e": optimized_stages,
        "baseline_stages_wh": {
            k: round(float(v), 4) for k, v in baseline.items() if k.endswith("_wh")
        },
        "optimized_stages_wh": {
            k: round(float(v), 4) for k, v in green.items() if k.endswith("_wh")
        },
        "map_tokens_by_tier": dict(map_by_tier),
        "map_tokens_total": map_tokens_total,
        "compile_tokens": compile_tokens,
        "compile_calls": compile_calls,
        "map_tier": map_tier,
        "compile_tier": compile_tier,
        "baseline_reference": baseline_ref,
        "baseline_j_per_token": baseline_j,
        "retrieved_chunk_cap": BASELINE_RETRIEVED_CHUNK_CAP,
        "routing_impact": routing,
        "chunk_breakdown": chunk_breakdown,
        "chunk_map_co2e_g_sum": round(chunk_map_co2_sum, 4),
        "map_inference_facility_co2e_g": round(map_facility_co2, 4),
        "uncertainty": uncertainty,
        "assumptions_panel": ASSUMPTIONS_PANEL_TEXT,
        "assumptions": {
            "pue": snap.pue,
            "infrastructure_factor": snap.infrastructure_factor,
            "reporting_boundary": snap.reporting_boundary,
            "j_per_token_typical": dict(snap.j_per_token_typical),
            "embedding_j_per_token": snap.embedding_j_per_token,
            "parsing_j_per_token": snap.parsing_j_per_token,
            "chunking_j_per_token": snap.chunking_j_per_token,
            "enable_uncertainty": snap.enable_uncertainty,
            "baseline_reference": baseline_ref,
            "baseline_j_per_token": baseline_j,
            "references": list(snap.references),
        },
        "calibration": {
            "reference": "GPT-4o mini medium query → J/token anchor",
            "reference_wh": GPT4O_MINI_MEDIUM_WH,
            "reference_tokens": GPT4O_MINI_REF_TOKENS,
            "j_per_token_medium": A.GPT4O_MINI_J_PER_TOKEN_TYPICAL,
            "baseline_frontier_j_per_token": baseline_j,
            "citation": "arXiv:2505.09598",
            "pue": A.PUE,
        },
        "equation": (
            "CO₂e(g) = (Σ tokens×J/token × PUE × INFRASTRUCTURE_FACTOR "
            "/ 3_600_000) × grid_intensity_gCO2e/kWh"
        ),
        "baseline_definition": (
            f"Naive single-frontier pipeline: all map+compile inference at "
            f"{baseline_ref} ({baseline_j} J/token); no smart routing."
        ),
        "optimized_definition": (
            "Carbon-aware routing: per-chunk Light/Medium/Heavy map tiers "
            "+ selected compile tier; shared stages identical to baseline."
        ),
    }

    return {
        "carbon_saved_grams": float(saved),
        "baseline_cost_gco2e": float(baseline_co2),
        "actual_cost_gco2e": float(actual_co2),
        "efficiency_percent": float(efficiency),
        "emissions_direction": emissions_direction,
        "estimated_baseline_pipeline_emissions_g": float(baseline_co2),
        "estimated_optimized_pipeline_emissions_g": float(actual_co2),
        "estimated_carbon_saved_g": float(saved),
        "estimated_reduction_percent": float(efficiency),
        "reporting_boundary": snap.reporting_boundary,
        "reporting_boundary_label": "Operational Emissions (Boundary A)",
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
        "grid_updated_at": grid_info.get("updated_at"),
        "input_tokens": int(input_tokens),
        "retrieved_context_tokens": int(retrieved_context_tokens),
        "generated_tokens": int(generated_tokens),
        "effective_tokens": int(effective_tokens),
        "chunk_breakdown": chunk_breakdown,
        "breakdown": breakdown,
        "routing_impact": routing,
        "uncertainty": uncertainty,
        "assumptions_panel": ASSUMPTIONS_PANEL_TEXT,
        "methodology": METHODOLOGY_TEXT,
        "pue": A.PUE,
        "baseline_reference": baseline_ref,
        "region_decision": region_decision_dict,
    }
