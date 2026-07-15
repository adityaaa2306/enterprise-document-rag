"""
Regression: empty final summary / deadline-aware map workers.
"""
from __future__ import annotations

import inspect
import time
from typing import Any, Dict, List

import pytest


def test_extractive_fallback_is_usable():
    from src.agents import models
    from src.core.pipeline_executor import _extractive_chunk_fallback

    fb = _extractive_chunk_fallback("Alpha beta gamma. " * 80)
    assert models._is_usable_summary(fb)
    assert "Extractive fallback" in fb
    assert "Alpha" in fb


def test_map_and_escalate_workers_are_deadline_aware():
    """Scheduler detects deadline_mono= on workers — param rename regression."""
    from src.core.execution_scheduler import _supports_deadline
    from src.core import pipeline_executor as pe

    # Build a minimal execute_document_dag to grab nested workers via source.
    src = inspect.getsource(pe.execute_document_dag)
    assert "def _run_chunk(payload, deadline_mono" in src
    assert "def _esc_one(payload, deadline_mono" in src
    assert "deadline_mono_inner" not in src


def test_dag_does_not_wipe_prior_summary_on_failed_escalate(monkeypatch):
    """Escalate soft-fail must keep a usable prior map summary."""
    from src.agents import summarization_agents
    from src.core import pipeline_executor as pe
    from src.core.config import settings

    class FakeChunk:
        def __init__(self, i):
            self.content = f"Important findings section {i}. " * 40
            self.section_path = f"S{i}"
            self.parent_id = "p0"

    chunks = [FakeChunk(i) for i in range(3)]
    state: Dict[str, Any] = {
        "job_id": "keep-prior",
        "chunks": chunks,
        "chunk_routing": [{"chunk_index": i, "tier": "light"} for i in range(3)],
        "routing_decision": {"tier": "light", "fallbacks": ["m1"]},
        "features": {"grid_intensity": 400.0},
        "pipeline_intelligence": {
            "strategy": {
                "hierarchy_fan_in": 8,
                "hierarchy_max_depth": 2,
                "skip_regional_below": 99,
                "qva_confidence_threshold": 0.99,  # force escalate
                "qva_compile_threshold": 0.01,
                "max_escalations": 1,
                "max_escalate_chunks": 8,
                "medium_first": True,
            }
        },
        "carbon_spent_g": 0.0,
        "agent_telemetry": [],
    }

    calls = {"n": 0}

    def fake_agent(text, st, *, tier, model_ids=None, **kw):
        calls["n"] += 1
        phase = "map" if calls["n"] <= 3 else "esc"
        if phase == "map":
            return summarization_agents.AgentRunResult(
                summary=f"Good map summary for {text[:40]}",
                tier=tier,
                model_id="light-1",
                latency_ms=10.0,
                input_tokens=10,
                output_tokens=20,
                carbon_estimate_g=0.01,
                confidence=0.9,
                success=True,
            )
        # Escalate returns unusable failure text (as NIM deadline soft-fail did)
        return summarization_agents.AgentRunResult(
            summary="Summary generation failed.",
            tier=tier,
            model_id="heavy-1",
            latency_ms=5.0,
            input_tokens=10,
            output_tokens=0,
            carbon_estimate_g=0.0,
            confidence=0.1,
            success=False,
        )

    monkeypatch.setattr(summarization_agents, "run_summarization_agent", fake_agent)
    monkeypatch.setattr(settings, "MAP_EMPTY_RETRY_ATTEMPTS", 1)
    monkeypatch.setattr(pe, "_run_with_hard_isolation", lambda fn, **kw: fn())

    # Short but nonzero job wall so escalate still runs.
    out = pe.execute_document_dag(state, deadline_mono=time.monotonic() + 120.0)
    summaries = out.get("summaries") or []
    assert len(summaries) == 3
    for s in summaries:
        assert "Good map summary" in s, f"prior wiped: {s[:120]!r}"
        assert "Summary generation failed" not in s
    final = str(out.get("final_summary") or "")
    assert final.strip()
    assert "Unable to generate a final summary" not in final


def test_past_deadline_uses_extractive_not_blank(monkeypatch):
    from src.agents import summarization_agents
    from src.core import pipeline_executor as pe

    class FakeChunk:
        def __init__(self, i):
            self.content = f"Document paragraph {i} with real content here. " * 20
            self.section_path = f"S{i}"
            self.parent_id = "p0"

    chunks = [FakeChunk(0)]
    state: Dict[str, Any] = {
        "job_id": "past-deadline",
        "chunks": chunks,
        "chunk_routing": [{"chunk_index": 0, "tier": "medium"}],
        "routing_decision": {"tier": "medium"},
        "features": {"grid_intensity": 400.0},
        "pipeline_intelligence": {
            "strategy": {
                "hierarchy_fan_in": 4,
                "hierarchy_max_depth": 2,
                "skip_regional_below": 99,
                "qva_confidence_threshold": 0.01,
                "qva_compile_threshold": 0.01,
                "max_escalations": 0,
            }
        },
        "carbon_spent_g": 0.0,
        "agent_telemetry": [],
    }

    def boom(*a, **k):
        raise AssertionError("NIM should not be called when deadline already past")

    monkeypatch.setattr(summarization_agents, "run_summarization_agent", boom)

    out = pe.execute_document_dag(state, deadline_mono=time.monotonic() - 1.0)
    s0 = (out.get("summaries") or [""])[0]
    assert "Extractive fallback" in s0
    assert "Document paragraph" in s0
    final = str(out.get("final_summary") or "")
    assert final.strip()
    assert "Unable to generate a final summary" not in final
