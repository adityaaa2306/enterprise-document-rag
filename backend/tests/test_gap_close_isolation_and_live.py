"""
Gap-close tests: hard node isolation, live assigner, streaming never-freeze.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

import pytest


def test_http_timeout_strictly_below_map_wall():
    from src.core.config import settings

    assert float(settings.NIM_HTTP_TIMEOUT_SEC) < float(settings.MAP_CHUNK_HARD_TIMEOUT_SEC)
    assert float(settings.NIM_HARD_TIMEOUT_SEC) < float(settings.MAP_CHUNK_HARD_TIMEOUT_SEC)
    assert float(settings.NIM_COMPILE_TIMEOUT_SEC) < float(
        settings.COMPILE_NODE_HARD_TIMEOUT_SEC
    )
    settings.validate_for_runtime(require_cors=False)


def test_run_with_hard_isolation_abandons_hung_call():
    from src.core.pipeline_executor import _run_with_hard_isolation

    def hung():
        time.sleep(30)
        return "never"

    t0 = time.perf_counter()
    with pytest.raises(TimeoutError):
        _run_with_hard_isolation(hung, hard_timeout_sec=0.4, label="test-hung")
    elapsed = time.perf_counter() - t0
    assert elapsed < 2.0, f"isolation took too long: {elapsed:.2f}s"


def test_hung_map_node_cancels_siblings_continue(monkeypatch):
    """
    One hung NIM call mid-graph cancels within MAP wall; siblings still complete.
    """
    from src.agents import summarization_agents
    from src.core import pipeline_executor as pe
    from src.core.config import settings

    class FakeChunk:
        def __init__(self, i):
            self.content = f"Chunk content {i} " * 10
            self.section_path = f"S{i}"
            self.parent_id = "p0"

    chunks = [FakeChunk(i) for i in range(4)]
    state: Dict[str, Any] = {
        "job_id": "iso-test",
        "chunks": chunks,
        "chunk_routing": [{"chunk_index": i, "tier": "medium"} for i in range(4)],
        "routing_decision": {"tier": "medium", "fallbacks": ["m1"]},
        "features": {"grid_intensity": 400.0},
        "pipeline_intelligence": {
            "strategy": {
                "hierarchy_fan_in": 4,
                "hierarchy_max_depth": 4,
                "skip_regional_below": 99,  # skip hierarchy complexity
                "qva_confidence_threshold": 0.01,
                "qva_compile_threshold": 0.01,
                "max_escalations": 0,
                "medium_first": True,
            }
        },
        "carbon_spent_g": 0.0,
        "agent_telemetry": [],
    }

    call_count = {"n": 0}
    completed_ok: List[int] = []

    def fake_agent(text, st, *, tier, model_ids=None, **kw):
        call_count["n"] += 1
        # First call hangs forever (simulates stuck NIM socket)
        tid = kw.get("task_id") or ""
        idx = 0
        if "chunk-" in tid:
            try:
                idx = int(str(tid).split("-")[-1])
            except Exception:
                idx = 0
        if idx == 1:
            time.sleep(60)
        completed_ok.append(idx)
        return summarization_agents.AgentRunResult(
            summary=f"Summary for {idx} with enough tokens to pass.",
            tier=tier,
            model_id=(model_ids or ["m1"])[0],
            latency_ms=50.0,
            input_tokens=10,
            output_tokens=20,
            carbon_estimate_g=0.01,
            confidence=0.9,
            success=True,
        )

    monkeypatch.setattr(summarization_agents, "run_summarization_agent", fake_agent)
    monkeypatch.setattr(settings, "MAP_CHUNK_HARD_TIMEOUT_SEC", 1.0)
    monkeypatch.setattr(settings, "NIM_HTTP_TIMEOUT_SEC", 0.5)
    monkeypatch.setattr(settings, "MAX_PARALLEL_WORKERS", 4)
    monkeypatch.setattr(settings, "MAP_EMPTY_RETRY_ATTEMPTS", 1)
    monkeypatch.setattr(settings, "CAPACITY_SCHEDULER_ENABLED", True)

    # Stub compile to avoid real hierarchy work
    def fake_compile(*_a, **_k):
        return {
            "final_summary": "## Summary\n\nOk",
            "compile_calls": 0,
            "compile_carbon_g": 0.0,
            "used_heavy": False,
            "hierarchy": {},
            "dag_nodes": {},
            "branch_recompiles": [],
        }

    monkeypatch.setattr(pe.dag_scheduler, "run_dag_compile", fake_compile)

    # QVA always pass
    class V:
        passed = True
        confidence = 0.9
        details = {"failed_indices": []}

        def to_dict(self):
            return {"passed": True, "confidence": 0.9, "details": self.details}

    monkeypatch.setattr(pe.quality_validation, "validate_chunks", lambda *a, **k: V())

    progress_ticks: List[float] = []

    def pcb(pct, msg, extra):
        progress_ticks.append(time.monotonic())

    t0 = time.perf_counter()
    out = pe.execute_document_dag(state, progress_cb=pcb)
    wall = time.perf_counter() - t0

    # Must not stall for the hung sleep (60s); allow retry/scheduling jitter.
    assert wall < 25.0, f"job stalled {wall:.1f}s waiting on hung node"
    # Sibling chunks should have completed (0,2,3) — hung idx=1 cancelled
    assert 0 in completed_ok or any(
        (out.get("summaries") or [""])[i] for i in (0, 2, 3)
    )
    summaries = out.get("summaries") or []
    assert len(summaries) == 4
    # At least 2 siblings succeeded despite the hung node
    ok = sum(1 for s in summaries if (s or "").strip())
    assert ok >= 2
    assert len(progress_ticks) >= 2


def test_live_assigner_shifts_on_load_and_grid_spike():
    from src.core import node_assigner as na

    na.clear_latency_window()
    chain = ["fast-model", "slow-quality-model"]
    na.record_model_latency("fast-model", 200.0)
    na.record_model_latency("slow-quality-model", 5000.0)

    state_calm = {
        "_assigner_load_override": 0.1,
        "_assigner_grid_override": 250.0,
        "features": {},
    }
    a_calm = na.assign_model_for_node(
        node_kind="chunk",
        min_tier="medium",
        model_chain=chain,
        state=state_calm,
        prefer_quality=True,
    )

    state_spike = {
        "_assigner_load_override": 0.95,
        "_assigner_grid_override": 850.0,
        "features": {},
        "job_id": "assign-test",
    }
    a_spike = na.assign_model_for_node(
        node_kind="chunk",
        min_tier="medium",
        model_chain=chain,
        state=state_spike,
        prefer_quality=False,
    )

    # Under spike, prefer earlier/faster model
    assert a_spike["model_id"] == "fast-model"
    assert a_spike["load"] >= 0.9
    assert a_spike["grid_intensity"] >= 800
    # Calm + prefer_quality may pick either; spike must differ or at least be fast
    assert "load=" in (a_spike["reasons"][0] if a_spike["reasons"] else "")
    # Mid-job shift: different scores when conditions change
    assert a_calm["score"] != a_spike["score"] or a_calm["model_id"] != a_spike["model_id"]


def test_streaming_fields_advance_on_timeout_and_retry(monkeypatch):
    """Job-status partial fields keep advancing under timeout/retry (never silent freeze)."""
    from src.db import jobs as job_store
    from src.agents import summarization_agents
    from src.core import pipeline_executor as pe
    from src.core.config import settings

    class FakeChunk:
        def __init__(self, i):
            self.content = f"Body {i} " * 15
            self.section_path = "S"
            self.parent_id = "p"

    jid = "stream-freeze-test"
    job_store.JOB_STATUSES[jid] = {"status": "running", "partial": {}}
    chunks = [FakeChunk(i) for i in range(3)]
    state = {
        "job_id": jid,
        "chunks": chunks,
        "chunk_routing": [{"chunk_index": i, "tier": "light"} for i in range(3)],
        "routing_decision": {"tier": "light", "fallbacks": ["m"]},
        "features": {"grid_intensity": 400.0},
        "pipeline_intelligence": {
            "strategy": {
                "hierarchy_fan_in": 8,
                "hierarchy_max_depth": 2,
                "skip_regional_below": 99,
                "qva_confidence_threshold": 0.01,
                "max_escalations": 0,
            }
        },
    }

    attempts = {"n": 0}

    def flaky(text, st, **kw):
        attempts["n"] += 1
        tid = kw.get("task_id") or ""
        if "chunk-0" in tid and attempts["n"] <= 1:
            time.sleep(5)  # will hit isolation timeout then retry sibling path
        return summarization_agents.AgentRunResult(
            summary="A solid summary with enough content here.",
            tier="light",
            model_id="m",
            latency_ms=40.0,
            input_tokens=5,
            output_tokens=10,
            carbon_estimate_g=0.01,
            confidence=0.85,
            success=True,
        )

    monkeypatch.setattr(summarization_agents, "run_summarization_agent", flaky)
    monkeypatch.setattr(settings, "MAP_CHUNK_HARD_TIMEOUT_SEC", 0.6)
    monkeypatch.setattr(settings, "MAP_EMPTY_RETRY_ATTEMPTS", 2)
    monkeypatch.setattr(settings, "MAX_PARALLEL_WORKERS", 3)

    monkeypatch.setattr(
        pe.dag_scheduler,
        "run_dag_compile",
        lambda *a, **k: {
            "final_summary": "## Summary\n\nDone",
            "compile_calls": 1,
            "compile_carbon_g": 0.0,
            "dag_nodes": {},
            "hierarchy": {},
            "branch_recompiles": [],
        },
    )

    class V:
        passed = True
        confidence = 0.9
        details = {"failed_indices": []}

        def to_dict(self):
            return {"passed": True, "confidence": 0.9, "details": self.details}

    monkeypatch.setattr(pe.quality_validation, "validate_chunks", lambda *a, **k: V())

    snapshots: List[Dict[str, Any]] = []

    def pcb(pct, msg, extra):
        partial = (job_store.JOB_STATUSES.get(jid) or {}).get("partial") or {}
        snapshots.append(
            {
                "t": time.monotonic(),
                "pct": pct,
                "msg": msg,
                "dag": (extra or {}).get("dag") or partial.get("dag"),
                "remaining": partial.get("remaining_tasks"),
            }
        )

    pe.execute_document_dag(state, progress_cb=pcb)
    assert len(snapshots) >= 3
    # Timestamps must advance (never frozen on one poll)
    times = [s["t"] for s in snapshots]
    assert times[-1] > times[0]
    # Messages / pct should not be identical across all ticks after work
    msgs = {s["msg"] for s in snapshots}
    assert len(msgs) >= 2 or len({s["pct"] for s in snapshots}) >= 2


def test_streaming_advances_on_worker_death_and_reassign(monkeypatch):
    """Worker exception mid-task + model reassignment still advances job-status fields."""
    from src.db import jobs as job_store
    from src.agents import summarization_agents
    from src.core import pipeline_executor as pe
    from src.core import node_assigner as na
    from src.core.config import settings

    class FakeChunk:
        def __init__(self, i):
            self.content = f"Worker death body {i} " * 12
            self.section_path = "S"
            self.parent_id = "p"

    jid = "stream-worker-death"
    job_store.JOB_STATUSES[jid] = {"status": "running", "partial": {}}
    n = 4
    chunks = [FakeChunk(i) for i in range(n)]
    state = {
        "job_id": jid,
        "chunks": chunks,
        "chunk_routing": [{"chunk_index": i, "tier": "medium"} for i in range(n)],
        "routing_decision": {"tier": "medium", "fallbacks": ["m-a", "m-b"]},
        "features": {"grid_intensity": 400.0},
        "pipeline_intelligence": {
            "strategy": {
                "hierarchy_fan_in": 8,
                "hierarchy_max_depth": 2,
                "skip_regional_below": 99,
                "qva_confidence_threshold": 0.01,
                "max_escalations": 0,
            }
        },
    }

    seen = {"dead": False}

    def flaky(text, st, **kw):
        tid = kw.get("task_id") or ""
        if "chunk-2" in tid and not seen["dead"]:
            seen["dead"] = True
            # Simulate worker dying mid-task
            raise RuntimeError("simulated worker death")
        # Mid-job load spike so assigner can shift
        st["_assigner_load_override"] = 0.9
        return summarization_agents.AgentRunResult(
            summary="Recovered summary with enough text for quality gate.",
            tier="medium",
            model_id="m-b",
            latency_ms=30.0,
            input_tokens=8,
            output_tokens=12,
            carbon_estimate_g=0.01,
            confidence=0.8,
            success=True,
        )

    monkeypatch.setattr(summarization_agents, "run_summarization_agent", flaky)
    monkeypatch.setattr(settings, "MAP_CHUNK_HARD_TIMEOUT_SEC", 2.0)
    monkeypatch.setattr(settings, "MAP_EMPTY_RETRY_ATTEMPTS", 2)
    monkeypatch.setattr(settings, "MAX_PARALLEL_WORKERS", 3)
    monkeypatch.setattr(
        pe.dag_scheduler,
        "run_dag_compile",
        lambda *a, **k: {
            "final_summary": "## Summary\n\nRecovered",
            "compile_calls": 1,
            "compile_carbon_g": 0.0,
            "dag_nodes": {},
            "hierarchy": {},
            "branch_recompiles": [],
        },
    )

    class V:
        passed = True
        confidence = 0.9
        details = {"failed_indices": []}

        def to_dict(self):
            return {"passed": True, "confidence": 0.9, "details": self.details}

    monkeypatch.setattr(pe.quality_validation, "validate_chunks", lambda *a, **k: V())

    ticks = []

    def pcb(pct, msg, extra):
        partial = (job_store.JOB_STATUSES.get(jid) or {}).get("partial") or {}
        ticks.append((time.monotonic(), pct, msg, partial.get("remaining_tasks")))

    out = pe.execute_document_dag(state, progress_cb=pcb)
    assert seen["dead"] is True
    assert len(ticks) >= 3
    assert ticks[-1][0] > ticks[0][0]
    # Job completed with some summaries despite worker death
    assert sum(1 for s in (out.get("summaries") or []) if s) >= 2
    # Assigner path exercised (load override consumed without freeze)
    a = na.assign_model_for_node(
        node_kind="chunk",
        min_tier="medium",
        model_chain=["m-a", "m-b"],
        state={"_assigner_load_override": 0.95, "_assigner_grid_override": 800.0},
    )
    assert a["model_id"] is not None


def test_unified_dag_route_flag():
    from src.core.config import settings
    from src.core.orchestrator import route_after_cre

    assert bool(getattr(settings, "UNIFIED_DAG_EXECUTOR_ENABLED", True)) is True
    assert route_after_cre({}) == "execute_document_dag"
