"""Unit tests for adaptive per-chunk router + carbon budget demotion."""
from src.core.chunk_router import route_chunks, routing_distribution


def test_routes_simple_to_light_and_hard_to_heavy():
    feats = [
        {
            "chunk_index": 0,
            "complexity": 0.15,
            "importance": 0.2,
            "technical_density": 0.05,
            "equation_count": 0,
            "section_type": "appendix",
            "token_count": 200,
            "named_entity_density": 0.1,
        },
        {
            "chunk_index": 1,
            "complexity": 0.9,
            "importance": 0.92,
            "technical_density": 0.8,
            "equation_count": 4,
            "section_type": "equation_heavy",
            "token_count": 1100,
            "named_entity_density": 0.5,
        },
    ]
    decisions = route_chunks(
        feats,
        cre_result={"min_tier": "light"},
        routing_decision={"tier": "medium", "selected_model": "m", "domain_risk": "general"},
        carbon_remaining_g=40.0,
        budget_enabled=True,
    )
    assert decisions[0].tier == "light"
    assert decisions[1].tier in ("medium", "heavy")
    assert "Assigned" in decisions[0].reason
    dist = routing_distribution(decisions)
    assert dist["total"] == 2
    assert dist["light"] + dist["medium"] + dist["heavy"] == 2


def test_budget_prefers_lighter_tiers():
    feats = [
        {
            "chunk_index": i,
            "complexity": 0.8,
            "importance": 0.85,
            "technical_density": 0.7,
            "equation_count": 2,
            "section_type": "technical",
            "token_count": 900,
            "named_entity_density": 0.4,
        }
        for i in range(5)
    ]
    decisions = route_chunks(
        feats,
        cre_result={"min_tier": "light"},
        routing_decision={"tier": "medium", "selected_model": "m"},
        carbon_remaining_g=0.5,
        budget_enabled=True,
    )
    # Under tight budget, should not all be heavy
    assert sum(1 for d in decisions if d.tier == "heavy") < len(decisions)
