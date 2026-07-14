"""Tests for Boundary-A operational carbon accounting (naive heavy baseline + per-chunk optimized)."""
from src.carbon import assumptions as A
from src.carbon.accounting import estimate_workflow_carbon
from src.carbon.energy_model import (
    GPT4O_MINI_MEDIUM_WH,
    GPT4O_MINI_REF_TOKENS,
    apply_facility_overhead,
    energy_to_co2e_g,
    estimate_baseline_energy,
    inference_joules,
    joules_to_kwh,
)
from src.core.frontier_carbon_compare import (
    FRONTIER_RELATIVE_INTENSITY,
    OUR_SYSTEM_NAME,
    build_frontier_comparison,
)
from src.core.scheduler import calculate_carbon_savings


class _Chunk:
    def __init__(self, content: str):
        self.content = content


def _grid(**kwargs):
    base = {
        "intensity_gco2_kwh": 643.0,
        "zone": "IN-WE",
        "datetime": "2026-07-13T11:00:00.000Z",
        "updated_at": "2026-07-13T06:04:36.124Z",
        "source": "test",
        "is_estimated": True,
    }
    base.update(kwargs)
    return base


def _doc_state(
    *,
    tier: str = "medium",
    compile_tier: str = "heavy",
    chunk_tiers: list | None = None,
    n_chunks: int = 28,
):
    body = (
        "RAG systems retrieve context and generate grounded answers with citations. " * 40
    )
    chunks = [_Chunk(body) for _ in range(n_chunks)]
    summary = (
        "Executive summary of the masterclass covering retrieval, ranking, "
        "generation, evaluation, and production architecture concerns. "
    ) * 40
    if chunk_tiers is None:
        chunk_tiers = [tier] * n_chunks
    assert len(chunk_tiers) == n_chunks
    chunk_routing = [
        {
            "chunk_index": i,
            "tier": chunk_tiers[i],
            "model": f"model-{chunk_tiers[i]}",
            "reason": "test",
        }
        for i in range(n_chunks)
    ]
    return {
        "chunks": chunks,
        "total_chunks": len(chunks),
        "chunks_escalated": 0,
        "final_summary": summary,
        "model_usage_chars": {
            "light": 0,
            "medium": sum(len(c.content) for c in chunks),
            "large": len(summary) * 3,
        },
        "routing_decision": {
            "tier": tier,
            "compile_tier": compile_tier,
            "selected_model": "mistralai/ministral-14b-instruct-2512",
        },
        "chunk_routing": chunk_routing,
    }


def test_no_baseline_serving_overhead_constant():
    import src.carbon.energy_model as em
    import src.carbon.assumptions as assumptions

    assert not hasattr(em, "BASELINE_SERVING_OVERHEAD")
    assert not hasattr(assumptions, "BASELINE_SERVING_OVERHEAD")


def test_energy_to_co2e_is_product():
    assert energy_to_co2e_g(0.061, 643.0) == 0.061 * 643.0


def test_j_per_token_anchor_matches_literature():
    expected = (GPT4O_MINI_MEDIUM_WH * 3600.0) / float(GPT4O_MINI_REF_TOKENS)
    assert abs(A.GPT4O_MINI_J_PER_TOKEN_TYPICAL - expected) < 1e-9
    assert abs(A.J_PER_TOKEN_TYPICAL["medium"] - expected) < 1e-9


def test_facility_overhead_is_only_pue():
    compute = 10_000.0
    facility = apply_facility_overhead(compute)
    assert abs(facility - compute * A.PUE * A.INFRASTRUCTURE_FACTOR) < 1e-9
    assert A.INFRASTRUCTURE_FACTOR == 1.0


def test_baseline_uses_heavy_inference():
    assert A.BASELINE_INFERENCE_TIER == "heavy"
    pack = estimate_baseline_energy(
        input_tokens=10000,
        retrieved_context_tokens=2000,
        generated_tokens=1000,
        map_tokens=12500,
        compile_tokens=3000,
        verification_tokens=400,
        baseline_j_per_token=A.J_PER_TOKEN_TYPICAL["heavy"],
    )
    expected_inf = 12500 * A.J_PER_TOKEN_TYPICAL["heavy"] + 3000 * A.J_PER_TOKEN_TYPICAL["heavy"]
    assert abs(pack["inference_j"] - expected_inf) < 1e-6
    assert pack["routing_j"] == 0.0


def test_baseline_matches_jtoken_pue_equation():
    inp, ret, map_tok, comp, verify = 10000, 2000, 12500, 3000, 400
    j = A.J_PER_TOKEN_TYPICAL["heavy"]
    pack = estimate_baseline_energy(
        input_tokens=inp,
        retrieved_context_tokens=ret,
        generated_tokens=1000,
        map_tokens=map_tok,
        compile_tokens=comp,
        verification_tokens=verify,
        baseline_j_per_token=j,
    )
    compute_j = (
        inp * A.PARSING_J_PER_TOKEN
        + inp * A.CHUNKING_J_PER_TOKEN
        + inp * A.EMBEDDING_J_PER_TOKEN
        + (A.RETRIEVAL_BASE_J + (ret / 350.0) * A.RETRIEVAL_J_PER_HIT)
        + map_tok * j
        + comp * j
        + verify * A.VERIFY_J_PER_TOKEN
    )
    expected_kwh = joules_to_kwh(compute_j * A.PUE)
    assert abs(pack["total_kwh"] - expected_kwh) < 1e-9


def test_workflow_report_has_stages_routing_uncertainty():
    report = estimate_workflow_carbon("job-test", _doc_state(), grid=_grid())
    baseline = report["baseline_cost_gco2e"]
    actual = report["actual_cost_gco2e"]
    assert baseline > 0 and actual > 0
    assert abs(report["carbon_saved_grams"] - (baseline - actual)) < 1e-9
    assert report["reporting_boundary_label"].startswith("Operational Emissions")
    assert "chunk_breakdown" in report
    assert len(report["chunk_breakdown"]) == 28

    bd = report["breakdown"]
    stages = bd["optimized_stages_gco2e"]
    assert "inference_gco2e" in stages
    assert abs(
        stages["total_gco2e"] - sum(v for k, v in stages.items() if k != "total_gco2e")
    ) < 0.02

    routing = report["routing_impact"]
    assert routing["total_chunks"] == 28
    assert routing["model_distribution"]["medium"] == 28

    unc = report["uncertainty"]
    assert unc["enabled"] is True
    assert report["pue"] == A.PUE


def test_all_heavy_optimized_near_baseline():
    """All-heavy routing ≈ naive frontier baseline (routing stub may differ slightly)."""
    grid = _grid(intensity_gco2_kwh=572.0)
    state = _doc_state(tier="heavy", compile_tier="heavy", chunk_tiers=["heavy"] * 28)
    report = estimate_workflow_carbon("job-heavy", state, grid=grid)
    # Optimized includes ROUTING_BASE_J; baseline does not — tiny positive delta allowed.
    assert report["actual_cost_gco2e"] >= report["baseline_cost_gco2e"] * 0.98
    assert report["actual_cost_gco2e"] <= report["baseline_cost_gco2e"] * 1.05
    # Savings near zero (may be slightly negative due to routing stub).
    assert abs(report["efficiency_percent"]) < 5.0


def test_light_routing_beats_heavy_baseline():
    grid = _grid(intensity_gco2_kwh=572.0)
    state = _doc_state(
        tier="light",
        compile_tier="medium",
        chunk_tiers=["light"] * 28,
    )
    report = estimate_workflow_carbon("job-light", state, grid=grid)
    assert report["actual_cost_gco2e"] < report["baseline_cost_gco2e"]
    assert report["carbon_saved_grams"] > 0
    assert report["efficiency_percent"] > 40.0
    assert report["emissions_direction"] == "reduced"


def test_per_chunk_mix_reflected_in_map_tokens():
    """7 light + 2 medium + 1 heavy must appear in map_tokens_by_tier."""
    n = 10
    tiers = ["light"] * 7 + ["medium"] * 2 + ["heavy"]
    state = _doc_state(
        tier="medium",
        compile_tier="heavy",
        chunk_tiers=tiers,
        n_chunks=n,
    )
    report = estimate_workflow_carbon("job-mix", state, grid=_grid())
    by = report["breakdown"]["map_tokens_by_tier"]
    assert by["light"] > 0 and by["medium"] > 0 and by["heavy"] > 0
    ri = report["routing_impact"]
    assert ri["light_chunks"] == 7
    assert ri["medium_chunks"] == 2
    assert ri["heavy_chunks"] == 1
    rows = report["chunk_breakdown"]
    assert len(rows) == 10
    assert sum(1 for r in rows if r["tier"] == "light") == 7
    # Σ chunk map CO₂ ≈ facility map CO₂
    assert abs(
        report["breakdown"]["chunk_map_co2e_g_sum"]
        - report["breakdown"]["map_inference_facility_co2e_g"]
    ) < 0.05


def test_signed_savings_not_clamped():
    """If somehow optimized > baseline, savings stay negative."""
    # Force via all-heavy + routing overhead: savings may be slightly negative.
    state = _doc_state(tier="heavy", compile_tier="heavy", chunk_tiers=["heavy"] * 10, n_chunks=10)
    report = estimate_workflow_carbon("job-neg", state, grid=_grid(intensity_gco2_kwh=700.0))
    expected = report["baseline_cost_gco2e"] - report["actual_cost_gco2e"]
    assert abs(report["carbon_saved_grams"] - expected) < 1e-9
    # Must NOT clamp to zero when negative
    if expected < 0:
        assert report["carbon_saved_grams"] < 0
        assert report["emissions_direction"] == "increased"


def test_chunk_accounting_equals_workflow_map():
    state = _doc_state(tier="light", compile_tier="medium", chunk_tiers=["light"] * 12, n_chunks=12)
    report = estimate_workflow_carbon("job-eq", state, grid=_grid())
    total_map = sum(report["breakdown"]["map_tokens_by_tier"].values())
    assert total_map == report["breakdown"]["map_tokens_total"]
    assert sum(r["map_tokens"] for r in report["chunk_breakdown"]) == total_map


def test_scheduler_delegates_to_workflow_engine():
    report = calculate_carbon_savings("job-sched", _doc_state())
    for key in (
        "baseline_cost_gco2e",
        "actual_cost_gco2e",
        "carbon_saved_grams",
        "efficiency_percent",
        "breakdown",
        "baseline_energy_kwh",
        "actual_energy_kwh",
        "routing_impact",
        "uncertainty",
        "chunk_breakdown",
    ):
        assert key in report


def test_green_uses_less_or_equal_energy_for_lighter_tier():
    grid = _grid(intensity_gco2_kwh=534.0)
    light = estimate_workflow_carbon(
        "job-light",
        _doc_state(tier="light", compile_tier="medium", chunk_tiers=["light"] * 28),
        grid=grid,
    )
    heavy = estimate_workflow_carbon(
        "job-heavy",
        _doc_state(tier="heavy", compile_tier="heavy", chunk_tiers=["heavy"] * 28),
        grid=grid,
    )
    assert light["actual_energy_kwh"] <= heavy["actual_energy_kwh"]
    assert light["actual_cost_gco2e"] < light["baseline_cost_gco2e"]


def test_frontier_comparison_from_workflow_report():
    report = estimate_workflow_carbon("job-viz", _doc_state(), grid=_grid())
    payload = build_frontier_comparison(report)
    assert payload["our_system"]["name"] == OUR_SYSTEM_NAME
    assert payload["summary_cards"]["heavy_model_baseline_gco2e"] == round(
        report["baseline_cost_gco2e"], 4
    )
    assert len(FRONTIER_RELATIVE_INTENSITY) == len(payload["comparison_models"])
    # GPT-4 (heavy J) should be near our naive baseline
    gpt4 = next(r for r in payload["comparison_models"] if r["model"] == "GPT-4")
    assert abs(gpt4["estimated_gco2e"] - round(report["baseline_cost_gco2e"], 1)) < 1.5


def test_reporting_boundary_enum_future_proof():
    assert A.ReportingBoundary.A_OPERATIONAL.value.startswith("A_")
    assert A.ReportingBoundary.B_OPERATIONAL_PLUS_EMBODIED.value.startswith("B_")
    assert A.ReportingBoundary.C_FULL_LIFECYCLE.value.startswith("C_")


def test_easy_medium_hard_savings_ordering():
    """Easy (all light) > medium mix > hard (all heavy) savings."""
    grid = _grid(intensity_gco2_kwh=600.0)
    easy = estimate_workflow_carbon(
        "easy",
        _doc_state(tier="light", compile_tier="medium", chunk_tiers=["light"] * 20, n_chunks=20),
        grid=grid,
    )
    medium = estimate_workflow_carbon(
        "med",
        _doc_state(
            tier="medium",
            compile_tier="heavy",
            chunk_tiers=["light"] * 10 + ["medium"] * 8 + ["heavy"] * 2,
            n_chunks=20,
        ),
        grid=grid,
    )
    hard = estimate_workflow_carbon(
        "hard",
        _doc_state(tier="heavy", compile_tier="heavy", chunk_tiers=["heavy"] * 20, n_chunks=20),
        grid=grid,
    )
    assert easy["efficiency_percent"] > medium["efficiency_percent"]
    assert medium["efficiency_percent"] > hard["efficiency_percent"]
    assert easy["carbon_saved_grams"] > medium["carbon_saved_grams"]
