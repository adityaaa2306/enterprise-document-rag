"""Tests for pipeline intelligence: capability, strategy, hierarchy, routing."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.core.document_capability import analyze_document_capability
from src.core.hierarchy import build_hierarchy_levels
from src.core.pipeline_intelligence import plan_pipeline_intelligence
from src.core.strategy_selector import select_processing_strategy
from src.core.chunk_router import route_chunks
from src.agents.quality_validation import validate_pair


def _chunk(text: str, i: int = 0, parent: str = "sec0", path: str = "Intro"):
    return SimpleNamespace(
        content=text,
        chunk_index=i,
        parent_id=parent,
        section_path=path,
        type="Text",
        chunk_kind="merged",
    )


class TestDocumentCapability:
    def test_tiny_scale(self):
        chunks = [_chunk("Short intro paragraph about the system." * 5, 0)]
        profile = analyze_document_capability(
            chunks,
            features={"reasoning_score": 0.3, "document_type": "memo"},
            chunk_features=[{"chunk_index": 0, "technical_density": 0.1}],
        )
        assert profile.document_scale in ("tiny", "small")
        assert profile.chunk_count == 1
        assert profile.estimated_tokens > 0

    def test_large_scale_from_tokens(self):
        # ~70k chars → ~17.5k tokens → small/medium; use many large chunks
        big = "technical methodology evaluation latency carbon " * 800
        chunks = [_chunk(big, i, f"s{i}", f"Chapter {i}") for i in range(40)]
        profile = analyze_document_capability(
            chunks,
            features={"reasoning_score": 0.7, "risk_level": "technical"},
            chunk_features=[
                {"chunk_index": i, "technical_density": 0.6, "complexity": 0.7}
                for i in range(40)
            ],
        )
        assert profile.document_scale in ("medium", "large", "xlarge")
        assert profile.chunk_count == 40


class TestStrategySelection:
    def test_tiny_single_pass(self):
        chunks = [_chunk("hello world " * 50)]
        profile = analyze_document_capability(chunks, features={"reasoning_score": 0.2})
        strat = select_processing_strategy(profile, job_mode="automatic", carbon_intensity=700)
        assert strat.map_mode == "single_pass"
        assert strat.compile_depth_label == "flat"
        assert strat.skip_regional_below >= 12

    def test_eco_mode_tightens_budget(self):
        chunks = [_chunk("x " * 2000, i) for i in range(12)]
        profile = analyze_document_capability(
            chunks, features={"reasoning_score": 0.5}
        )
        auto = select_processing_strategy(profile, job_mode="automatic", carbon_intensity=400)
        eco = select_processing_strategy(profile, job_mode="lowest_carbon", carbon_intensity=400)
        assert eco.carbon_budget_g < auto.carbon_budget_g
        assert eco.prefer_light_under_carbon is True

    def test_quality_mode_allows_heavy(self):
        chunks = [_chunk("complex theorem proof " * 100, i) for i in range(20)]
        profile = analyze_document_capability(
            chunks,
            features={"reasoning_score": 0.8, "risk_level": "legal"},
        )
        strat = select_processing_strategy(
            profile, job_mode="highest_quality", carbon_intensity=100
        )
        assert strat.compile_tier_hint == "heavy"
        assert strat.verification_strategy == "strict"


class TestAdaptiveHierarchy:
    def test_skip_regional_for_tiny(self):
        chunks = [_chunk(f"body {i}", i) for i in range(3)]
        summaries = [f"sum {i}" for i in range(3)]
        levels = build_hierarchy_levels(
            chunks, summaries, fan_in=8, max_depth=3, skip_regional_below=10
        )
        kinds = [lv["kind"] for lv in levels]
        assert "chunk" in kinds
        assert "regional" not in kinds

    def test_max_depth_respected(self):
        chunks = [_chunk(f"body {i}", i, f"p{i}", f"S{i}") for i in range(30)]
        summaries = [f"sum {i}" for i in range(30)]
        levels = build_hierarchy_levels(
            chunks, summaries, fan_in=3, max_depth=4, skip_regional_below=0
        )
        assert len(levels) <= 4


class TestRoutingIntelligence:
    def test_high_grid_prefer_light_demotes_heavy(self):
        feats = [
            {
                "chunk_index": 0,
                "complexity": 0.9,
                "importance": 0.9,
                "technical_density": 0.9,
                "equation_count": 3,
                "section_type": "technical",
                "token_count": 800,
            }
        ]
        decisions = route_chunks(
            feats,
            cre_result={"min_tier": "light"},
            routing_decision={"tier": "medium", "selected_model": "m"},
            strategy={"prefer_light_under_carbon": True, "heavy_quality_gain_min": 0.05},
            carbon_intensity=700,
            budget_enabled=False,
        )
        assert decisions[0].tier in ("medium", "light")
        assert "Grid=" in decisions[0].reason


class TestValidationMetrics:
    def test_pair_exposes_quality_and_fact_consistency(self):
        v = validate_pair(
            "The system saved 42 percent carbon in 2024 using adaptive routing.",
            "The system saved 42 percent carbon using adaptive routing.",
        )
        assert "quality_estimate" in v.details
        assert "fact_consistency" in v.details
        assert v.confidence > 0.4


class TestPlanPipeline:
    def test_plan_returns_profile_strategy_report(self):
        chunks = [_chunk("Introduction to green RAG systems. " * 40, i) for i in range(4)]
        intel = plan_pipeline_intelligence(
            chunks=chunks,
            features={"reasoning_score": 0.45, "document_type": "technical_documentation"},
            chunk_features=[
                {"chunk_index": i, "technical_density": 0.4, "complexity": 0.4}
                for i in range(4)
            ],
            triage_meta={"section_count": 4, "structure_diagnostics": {"merged_sections": 4}},
            job_mode="automatic",
            carbon_intensity=572,
        )
        assert intel["capability_profile"]["document_scale"]
        assert intel["strategy"]["strategy_id"]
        assert intel["report"]["why_strategy"]
        assert intel["policy_version"]
