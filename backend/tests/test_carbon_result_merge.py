"""Additive carbon merge + region promotion regression tests."""
from __future__ import annotations

from src.core.carbon_result_merge import (
    additive_dict_merge,
    promote_carbon_from_region_decision,
)
from src.core.processing_insights import build_processing_insights
from src.api.schemas import CarbonData, SummaryResponse


def test_promote_lifts_region_intensity_without_inventing():
    cd = {
        "actual_cost_gco2e": 13.2,
        "baseline_cost_gco2e": 23.2,
        "local_grid_gco2_kwh": 0.0,
        "compute_location": "unknown",
        "region_decision": {
            "selected_region_name": "India",
            "grid_carbon_intensity_gco2_kwh": 643.0,
            "grid_zone": "IN-WE",
            "provider": "electricity_maps",
            "grid": {"intensity_gco2_kwh": 643.0, "zone": "IN-WE"},
        },
    }
    out = promote_carbon_from_region_decision(cd)
    assert out["local_grid_gco2_kwh"] == 643.0
    assert out["compute_location"] == "India"
    assert out["grid_zone"] == "IN-WE"


def test_promote_does_not_invent_when_region_missing():
    cd = {"actual_cost_gco2e": 1.0}
    out = promote_carbon_from_region_decision(cd)
    assert "local_grid_gco2_kwh" not in out or out.get("local_grid_gco2_kwh") is None
    assert out.get("compute_location") in (None, "unknown") or "compute_location" not in out


def test_additive_merge_does_not_wipe_routing():
    base = {
        "routing_distribution": {"light": 8, "medium": 3, "heavy": 0, "total": 11},
        "carbon_data": {"operational_co2e_g": 13.2},
    }
    overlay = {
        "routing_distribution": {},
        "carbon_data": {"baseline_cost_gco2e": 23.0, "local_grid_gco2_kwh": 643.0},
    }
    out = additive_dict_merge(
        base,
        overlay,
        overlay_wins_keys={"baseline_cost_gco2e", "local_grid_gco2_kwh"},
    )
    # empty overlay routing must not wipe populated base
    assert out["routing_distribution"]["light"] == 8
    assert out["carbon_data"]["operational_co2e_g"] == 13.2
    assert out["carbon_data"]["baseline_cost_gco2e"] == 23.0


def test_summary_response_allows_partial_carbon_without_fake_grid():
    payload = {
        "document_id": "j1",
        "filename": "a.pdf",
        "final_summary": "hello",
        "job_id": "j1",
        "carbon_data": {
            "operational_co2e_g": 13.2,
            "actual_cost_gco2e": 13.2,
            "total_chunks": 11,
            # no local_grid / compute_location — must validate as None, not 0/unknown
        },
    }
    model = SummaryResponse.model_validate(payload)
    assert model.carbon_data.local_grid_gco2_kwh is None
    assert model.carbon_data.compute_location is None


def test_document_profile_exposes_complexity_alias():
    pi = build_processing_insights(
        routing_decision={"document_type": "technical_documentation", "tier": "light"},
        routing_distribution={"light": 8, "medium": 3, "heavy": 0, "total": 11},
        chunk_routing=[{"chunk_index": 0, "tier": "light", "model": "m"}],
        pipeline_intelligence={
            "capability_profile": {
                "complexity_class": "moderate",
                "document_scale": "small",
            },
            "strategy": {"name": "adaptive"},
            "report": {"accuracy_estimate": 0.8},
        },
    )
    assert pi["document_profile"]["complexity"] == "moderate"
    assert pi["document_type"] == "technical_documentation"
    assert pi["routing_distribution"]["light"] == 8
    assert len(pi["chunk_routing_sample"]) == 1
