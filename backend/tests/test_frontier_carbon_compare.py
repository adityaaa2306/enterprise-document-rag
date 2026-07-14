"""Unit tests for frontier comparison visualization (J/token based)."""
from src.carbon import assumptions as A
from src.core.frontier_carbon_compare import (
    FRONTIER_MODEL_J_PER_TOKEN,
    FRONTIER_RELATIVE_INTENSITY,
    OUR_SYSTEM_NAME,
    build_frontier_comparison,
)


def test_comparison_reprices_inference_not_baseline_times_factor():
    medium_j = A.J_PER_TOKEN_TYPICAL["medium"]
    carbon = {
        "baseline_cost_gco2e": 30.0,
        "actual_cost_gco2e": 30.0,
        "carbon_saved_grams": 0.0,
        "efficiency_percent": 0.0,
        "total_chunks": 48,
        "baseline_energy_kwh": 0.048,
        "local_grid_gco2_kwh": 625.0,
        "input_tokens": 20000,
        "reporting_boundary_label": "Operational Emissions (Boundary A)",
        "breakdown": {
            "input_tokens": 20000,
            "retrieved_context_tokens": 4000,
            "generated_tokens": 2000,
            "effective_tokens": 26000,
            "compile_tokens": 4000,
            "map_tokens_total": 25000,
            "map_tokens_by_tier": {"medium": 25000},
            "baseline_stages_gco2e": {
                "parsing_gco2e": 0.01,
                "chunking_gco2e": 0.01,
                "embedding_gco2e": 0.2,
                "retrieval_gco2e": 0.02,
                "routing_gco2e": 0.01,
                "inference_gco2e": 25.0,
                "verification_gco2e": 0.01,
                "infrastructure_gco2e": 4.0,
                "total_gco2e": 29.26,
            },
            "grid_carbon_intensity_gco2_kwh": 625.0,
        },
    }
    payload = build_frontier_comparison(carbon)
    by_model = {row["model"]: row for row in payload["comparison_models"]}

    # Effective-token serving at medium-class J stays in a realistic band.
    assert by_model["Llama 4 Maverick"]["estimated_gco2e"] < 40.0
    assert by_model["GPT-4"]["estimated_gco2e"] > by_model["Llama 4 Maverick"]["estimated_gco2e"]
    # Document-scale frontier bars must stay well below legacy 100g+ charts.
    assert by_model["GPT-o3"]["estimated_gco2e"] < 55.0
    assert by_model["GPT-4"]["estimated_gco2e"] < 50.0
    # Must NOT equal old baseline × 2.2 silent multiplier (30 × 2.2 = 66).
    assert by_model["GPT-o3"]["estimated_gco2e"] != round(30.0 * 2.20, 1)
    assert abs(by_model["GPT-4"]["relative_factor"] - (6.5 / medium_j)) < 0.01
    assert payload["our_system"]["name"] == OUR_SYSTEM_NAME
    assert payload["summary_cards"]["actual_emissions_gco2e"] == 30.0
    assert payload["summary_cards"]["heavy_model_baseline_gco2e"] == 30.0


def test_stale_chunk_baseline_rebuilt_from_energy():
    carbon = {
        "baseline_cost_gco2e": 252.0,  # legacy chunks × 5.25
        "actual_cost_gco2e": 21.6,
        "baseline_energy_kwh": 0.05,
        "local_grid_gco2_kwh": 572.0,
        "carbon_saved_grams": 0,
        "efficiency_percent": 0,
        "breakdown": {
            "input_tokens": 10000,
            "compile_tokens": 2000,
            "map_tokens_by_tier": {"medium": 12500},
            "baseline_stages_gco2e": {
                "inference_gco2e": 24.0,
                "embedding_gco2e": 0.3,
                "infrastructure_gco2e": 3.5,
                "total_gco2e": 28.6,
            },
        },
    }
    payload = build_frontier_comparison(carbon)
    # 0.05 * 572 = 28.6
    assert payload["summary_cards"]["heavy_model_baseline_gco2e"] == 28.6
    assert payload["comparison_models"][0]["estimated_gco2e"] < 100.0


def test_mapping_constant_order():
    names = [n for n, _ in FRONTIER_MODEL_J_PER_TOKEN]
    assert names[0] == "GPT-o3"
    assert "Gemma 3" in names
    assert len(FRONTIER_RELATIVE_INTENSITY) == len(FRONTIER_MODEL_J_PER_TOKEN)


def test_empty_carbon_data_is_safe():
    payload = build_frontier_comparison({})
    assert payload["our_system"]["carbon"] == 0.0
    assert all(row["estimated_gco2e"] == 0.0 for row in payload["comparison_models"])
