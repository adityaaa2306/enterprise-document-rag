"""Tests for workflow energy → Electricity Maps → CO₂e accounting."""
from src.carbon.accounting import estimate_workflow_carbon
from src.carbon.energy_model import (
    GPT4O_MINI_WH_PER_TOKEN,
    energy_to_co2e_g,
    estimate_baseline_energy_wh,
    wh_to_kwh,
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


def _doc_state(*, pages: int = 42, tier: str = "medium", compile_tier: str = "heavy"):
    # ~22k tokens of body text across capped chunks (matches redesign example scale)
    body = ("RAG systems retrieve context and generate grounded answers with citations. " * 40)
    chunks = [_Chunk(body) for _ in range(28)]
    summary = (
        "Executive summary of the masterclass covering retrieval, ranking, "
        "generation, evaluation, and production architecture concerns. "
    ) * 40
    return {
        "chunks": chunks,
        "total_chunks": len(chunks),
        "chunks_escalated": 2,
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
    }


def test_energy_to_co2e_is_product():
    assert energy_to_co2e_g(0.061, 643.0) == 0.061 * 643.0


def test_baseline_scales_with_effective_tokens_not_chunks():
    a = estimate_baseline_energy_wh(
        input_tokens=10000, retrieved_context_tokens=2000, generated_tokens=1000
    )
    b = estimate_baseline_energy_wh(
        input_tokens=20000, retrieved_context_tokens=2000, generated_tokens=1000
    )
    assert b["total_wh"] > a["total_wh"]
    assert a["effective_tokens"] == 13000


def test_workflow_report_realistic_band_with_fixed_grid():
    grid = {
        "intensity_gco2_kwh": 643.0,
        "zone": "IN-WE",
        "datetime": "2026-07-13T11:00:00.000Z",
        "updated_at": "2026-07-13T06:04:36.124Z",
        "source": "test",
        "is_estimated": True,
    }
    report = estimate_workflow_carbon("job-test", _doc_state(), grid=grid)
    baseline = report["baseline_cost_gco2e"]
    actual = report["actual_cost_gco2e"]
    assert 15.0 <= baseline <= 80.0, baseline
    assert 0.0 < actual < baseline
    assert report["carbon_saved_grams"] == max(0.0, baseline - actual)
    assert 0.0 <= report["efficiency_percent"] <= 100.0
    assert report["breakdown"]["grid_carbon_intensity_gco2_kwh"] == 643.0
    assert report["baseline_energy_kwh"] > 0
    assert report["actual_energy_kwh"] > 0
    # Must be energy × intensity, not token × gram factor
    assert abs(
        report["baseline_cost_gco2e"]
        - energy_to_co2e_g(report["baseline_energy_kwh"], 643.0)
    ) < 1e-6


def test_scheduler_delegates_to_workflow_engine():
    grid = {
        "intensity_gco2_kwh": 534.0,
        "zone": "IN-WE",
        "datetime": "2026-07-13T11:00:00.000Z",
        "source": "test",
        "is_estimated": True,
    }
    # Patch via passing state; scheduler calls estimate_workflow_carbon which hits live API.
    # Use accounting directly for determinism already covered; ensure scheduler returns keys.
    report = calculate_carbon_savings("job-sched", _doc_state())
    for key in (
        "baseline_cost_gco2e",
        "actual_cost_gco2e",
        "carbon_saved_grams",
        "efficiency_percent",
        "breakdown",
        "baseline_energy_kwh",
        "actual_energy_kwh",
    ):
        assert key in report


def test_green_uses_less_energy_than_baseline_for_light_tier():
    grid = {
        "intensity_gco2_kwh": 534.0,
        "zone": "IN-WE",
        "datetime": "2026-07-13T11:00:00.000Z",
        "source": "test",
        "is_estimated": False,
    }
    light = estimate_workflow_carbon(
        "job-light", _doc_state(tier="light", compile_tier="medium"), grid=grid
    )
    heavy = estimate_workflow_carbon(
        "job-heavy", _doc_state(tier="heavy", compile_tier="heavy"), grid=grid
    )
    assert light["actual_energy_kwh"] <= heavy["actual_energy_kwh"]


def test_frontier_comparison_from_workflow_report():
    grid = {
        "intensity_gco2_kwh": 643.0,
        "zone": "IN-WE",
        "datetime": "2026-07-13T11:00:00.000Z",
        "source": "test",
        "is_estimated": True,
    }
    report = estimate_workflow_carbon("job-viz", _doc_state(), grid=grid)
    payload = build_frontier_comparison(report)
    assert payload["our_system"]["name"] == OUR_SYSTEM_NAME
    assert payload["summary_cards"]["heavy_model_baseline_gco2e"] == round(
        report["baseline_cost_gco2e"], 4
    )
    assert len(FRONTIER_RELATIVE_INTENSITY) == len(payload["comparison_models"])
    assert "Energy" in payload["methodology"] or "energy" in payload["methodology"]


def test_wh_per_token_calibration_constant():
    assert GPT4O_MINI_WH_PER_TOKEN == 1.418 / 2000
    assert wh_to_kwh(1000) == 1.0
