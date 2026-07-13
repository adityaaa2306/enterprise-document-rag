"""Unit tests for frontier comparison visualization (workflow CO₂e based)."""
from src.core.frontier_carbon_compare import (
    FRONTIER_RELATIVE_INTENSITY,
    OUR_SYSTEM_NAME,
    build_frontier_comparison,
)


def test_comparison_uses_baseline_times_factor():
    carbon = {
        "baseline_cost_gco2e": 39.2,
        "actual_cost_gco2e": 11.6,
        "carbon_saved_grams": 27.6,
        "efficiency_percent": 70.4,
        "total_chunks": 24,
        "methodology": "energy × grid",
        "baseline_energy_kwh": 0.061,
        "local_grid_gco2_kwh": 643.0,
    }
    payload = build_frontier_comparison(carbon)
    by_model = {row["model"]: row for row in payload["comparison_models"]}
    assert by_model["GPT-4o"]["estimated_gco2e"] == round(39.2 * 1.40, 1)
    assert by_model["GPT-o3"]["estimated_gco2e"] == round(39.2 * 2.20, 1)
    assert payload["our_system"]["name"] == OUR_SYSTEM_NAME
    assert payload["summary_cards"]["actual_emissions_gco2e"] == 11.6
    assert payload["summary_cards"]["heavy_model_baseline_gco2e"] == 39.2
    # Realistic band — not legacy chunk×grams (~252)
    assert all(row["estimated_gco2e"] < 120 for row in payload["comparison_models"])


def test_stale_chunk_baseline_rebuilt_from_energy():
    carbon = {
        "baseline_cost_gco2e": 252.0,  # legacy chunks × 5.25
        "actual_cost_gco2e": 21.6,
        "baseline_energy_kwh": 0.05,
        "local_grid_gco2_kwh": 572.0,
        "carbon_saved_grams": 0,
        "efficiency_percent": 0,
    }
    payload = build_frontier_comparison(carbon)
    # 0.05 * 572 = 28.6
    assert payload["summary_cards"]["heavy_model_baseline_gco2e"] == 28.6
    assert payload["comparison_models"][0]["estimated_gco2e"] == round(28.6 * 2.20, 1)


def test_mapping_constant_order():
    names = [n for n, _ in FRONTIER_RELATIVE_INTENSITY]
    assert names[0] == "GPT-o3"
    assert "Gemma 3" in names


def test_empty_carbon_data_is_safe():
    payload = build_frontier_comparison({})
    assert payload["our_system"]["carbon"] == 0.0
    assert all(row["estimated_gco2e"] == 0.0 for row in payload["comparison_models"])
