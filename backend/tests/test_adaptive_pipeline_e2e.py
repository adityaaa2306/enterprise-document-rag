"""
E2E smoke for adaptive pipeline graph nodes with mocked summarizer/compile.
"""
from __future__ import annotations

from typing import Any, Dict, List

import src.agents.models as models
import src.agents.summarization_agents as sa
from src.agents.chunk_features import extract_chunk_features
from src.core import chunk_router, hierarchy
from src.core.orchestrator import (
    cre_and_route,
    extract_features_node,
    map_summarize_routed,
    reduce_compile,
    validate_map,
    escalate_once,
    should_escalate,
)


class Chunk:
    def __init__(self, content: str, parent_id: str, section_path: str):
        self.content = content
        self.parent_id = parent_id
        self.section_path = section_path
        self.type = "Text"
        self.chunk_kind = "text"


def test_adaptive_pipeline_smoke(monkeypatch):
    chunks = [
        Chunk("Simple appendix text about references. " * 20, "p1", "Appendix"),
        Chunk(
            "Complex theorem gradient optimizer covariance neural latency. " * 30
            + " $E=mc^2$ equation derivation. ",
            "p2",
            "Methods",
        ),
        Chunk("Results table narrative discussion methods. " * 25, "p2", "Methods"),
    ]

    def fake_tier(text, state, tier="medium", model_ids=None, call_meta=None):
        if call_meta is not None:
            call_meta["success"] = True
            call_meta["model_id"] = f"fake-{tier}"
            call_meta["call_ms"] = 5.0
        return f"SUMMARY({tier}): " + " ".join(str(text).split()[:40])

    def fake_compile(summaries, state, model_ids=None, deadline_mono=None):
        if isinstance(summaries, list):
            body = " ".join(str(s) for s in summaries)[:500]
        else:
            body = str(summaries)[:500]
        return "## Summary\n" + body

    monkeypatch.setattr(models, "run_tier_summarizer", fake_tier)
    monkeypatch.setattr(models, "run_compile_with_models", fake_compile)
    monkeypatch.setattr(
        sa,
        "run_summarization_agent",
        lambda text, state, tier="medium", model_ids=None, grid_intensity=500.0: sa.AgentRunResult(
            summary=fake_tier(text, state, tier=tier, model_ids=model_ids, call_meta={}),
            tier=tier,
            model_id=f"fake-{tier}",
            latency_ms=5.0,
            input_tokens=50,
            output_tokens=40,
            carbon_estimate_g=0.1 if tier == "light" else 0.2 if tier == "medium" else 0.4,
            confidence=0.9,
            success=True,
        ),
    )

    state: Dict[str, Any] = {
        "job_id": "test-adapt",
        "document_id": "test-adapt",
        "file_path": "x.pdf",
        "file_type": "pdf",
        "job_mode": "automatic",
        "chunks": chunks,
        "total_chunks": len(chunks),
        "summaries": [],
        "model_usage_chars": {"light": 0, "medium": 0, "large": 0},
        "models_used": [],
        "escalation_count": 0,
        "accept_with_warning": False,
        "chunks_escalated": 0,
        "ingestion_latency": {},
        "features": {
            "reasoning_score": 0.4,
            "structural_score": 0.3,
            "coherence_score": 0.3,
            "retrieval_confidence": 0.7,
            "document_type": "technical_documentation",
            "domain_risk": "general",
            "ocr_confidence": 0.9,
            "nim_available": True,
        },
        "triage_meta": {"strategy": "fast", "adaptive": True},
        "chunk_parents": [],
    }

    # Features
    out = extract_features_node(state)
    state.update(out)
    assert state["chunk_features"]
    assert len(state["chunk_features"]) == 3

    out = cre_and_route(state)
    state.update(out)
    assert state["chunk_routing"]
    assert state["carbon_budget_g"] == 40.0
    assert "routing_distribution" in state

    out = map_summarize_routed(state)
    state.update(out)
    assert len(state["summaries"]) == 3
    assert all(state["summaries"])

    out = validate_map(state)
    state.update(out)
    # Force a failed validation path once
    state["validation_verdict"] = {
        "passed": False,
        "confidence": 0.2,
        "codes": ["low_confidence"],
        "details": {"failed_indices": [1], "chunk_confidences": [0.9, 0.1, 0.8]},
    }
    assert should_escalate(state) == "escalate"
    out = escalate_once(state)
    state.update(out)
    assert state["escalation_count"] == 1
    assert state["chunks_escalated"] >= 1

    # Pass validation to compile
    state["validation_verdict"] = {
        "passed": True,
        "confidence": 0.8,
        "codes": [],
        "details": {"failed_indices": [], "pass_rate": 1.0},
    }
    assert should_escalate(state) == "compile"

    out = reduce_compile(state)
    state.update(out)
    assert state["final_summary"]
    assert "compile_meta" in state

    levels = hierarchy.build_hierarchy_levels(chunks, state["summaries"], fan_in=2)
    assert levels[0]["kind"] == "chunk"
