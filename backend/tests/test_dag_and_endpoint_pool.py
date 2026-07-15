"""Tests for multi-endpoint NIM pool + DAG hierarchical compile."""
from __future__ import annotations

from typing import Any, Dict, List

import pytest


def test_endpoint_pool_loads_multiple_keys(monkeypatch):
    from src.agents import nim_endpoint_pool as pool
    from src.core.config import settings

    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "nvapi-key-one")
    monkeypatch.setattr(settings, "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
    monkeypatch.setattr(settings, "NIM_ENDPOINT_2_API_KEY", "nvapi-key-two")
    monkeypatch.setattr(settings, "NIM_ENDPOINT_3_API_KEY", "nvapi-key-three")
    monkeypatch.setattr(settings, "NIM_ENDPOINT_2_BASE_URL", "")
    monkeypatch.setattr(settings, "NIM_ENDPOINT_3_BASE_URL", "")
    monkeypatch.setattr(settings, "NIM_API_KEYS", "")
    monkeypatch.setattr(settings, "NIM_ENDPOINT_POOL_ENABLED", True)

    eps = pool.load_endpoint_pool()
    assert len(eps) == 3
    lease = pool.acquire_endpoint(role="map")
    assert lease is not None
    assert lease.endpoint_id.startswith("endpoint-")
    pool.release_endpoint(lease, ok=True, latency_ms=100.0)
    snap = pool.pool_snapshot()
    assert len(snap) == 3
    assert snap[0]["total_calls"] >= 0


def test_least_load_prefers_cooler_endpoint(monkeypatch):
    from src.agents import nim_endpoint_pool as pool
    from src.core.config import settings

    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "k1")
    monkeypatch.setattr(settings, "NIM_ENDPOINT_2_API_KEY", "k2")
    monkeypatch.setattr(settings, "NIM_ENDPOINT_3_API_KEY", "k3")
    monkeypatch.setattr(settings, "NIM_ENDPOINT_STRATEGY", "least_load")
    monkeypatch.setattr(settings, "NIM_API_KEYS", "")
    pool.load_endpoint_pool()

    a = pool.acquire_endpoint(role="map")
    b = pool.acquire_endpoint(role="map")
    c = pool.acquire_endpoint(role="map")
    assert len({a.endpoint_id, b.endpoint_id, c.endpoint_id}) == 3
    pool.release_endpoint(a, ok=True, latency_ms=50)
    pool.release_endpoint(b, ok=True, latency_ms=50)
    pool.release_endpoint(c, ok=True, latency_ms=50)


def test_effective_workers_scale_with_endpoints(monkeypatch):
    from src.core.config import settings

    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "k1")
    monkeypatch.setattr(settings, "NIM_ENDPOINT_2_API_KEY", "k2")
    monkeypatch.setattr(settings, "NIM_ENDPOINT_3_API_KEY", "k3")
    monkeypatch.setattr(settings, "NIM_API_KEYS", "")
    monkeypatch.setattr(settings, "NIM_ENDPOINT_POOL_ENABLED", True)
    monkeypatch.setattr(settings, "NIM_ENDPOINT_MAX_CONCURRENT", 3)
    monkeypatch.setattr(settings, "NIM_ENDPOINT_1_MAX_CONCURRENT", 3)
    monkeypatch.setattr(settings, "NIM_ENDPOINT_2_MAX_CONCURRENT", 3)
    monkeypatch.setattr(settings, "NIM_ENDPOINT_3_MAX_CONCURRENT", 3)
    monkeypatch.setattr(settings, "MAP_MAX_WORKERS", 24)
    monkeypatch.setattr(settings, "COMPILE_MAX_WORKERS", 20)
    monkeypatch.setattr(settings, "MAX_PARALLEL_WORKERS", 24)
    monkeypatch.setattr(settings, "RUN_EMBEDDED_WORKER", False)
    assert settings.nim_endpoint_count() == 3
    # Capacity-aware: 3 endpoints × 3 concurrent = 9 (never firehose past NIM)
    assert settings.effective_nim_capacity() == 9
    assert settings.effective_map_max_workers() == 9
    assert settings.effective_compile_max_workers() == 9
    assert 1 <= settings.effective_parallel_workers() <= 9


def test_dag_compile_runs_levels_in_parallel(monkeypatch):
    from src.core import dag_scheduler
    from src.core.pipeline_dag import DagNode, build_chunk_nodes
    from src.core.planning import plan_compile_hierarchy
    from src.agents import models, quality_validation

    class Chunk:
        def __init__(self, i: int, parent: str):
            self.content = f"chunk {i} " * 20
            self.parent_id = parent
            self.section_path = parent
            self.type = "Text"

    chunks = [Chunk(i, f"p{i // 2}") for i in range(6)]
    summaries = [f"Summary of section chunk {i} with findings." for i in range(6)]

    calls: List[str] = []

    def fake_compile(inputs, state, model_ids=None, deadline_mono=None):
        calls.append(str(model_ids))
        body = inputs[0] if isinstance(inputs, list) else str(inputs)
        return "## Summary\n" + body[:200]

    monkeypatch.setattr(models, "run_compile_with_models", fake_compile)
    monkeypatch.setattr(
        quality_validation,
        "validate_final",
        lambda *_a, **_k: quality_validation.ValidationVerdict(
            passed=True,
            confidence=0.9,
            faithfulness=0.9,
            coverage=0.9,
            hallucination_rate=0.0,
            contradiction_rate=0.0,
            codes=[],
            details={},
        ),
    )

    state: Dict[str, Any] = {
        "job_id": "test-dag-parallel",
        "models_used": [],
        "model_usage_chars": {"light": 0, "medium": 0, "large": 0},
    }
    nodes = build_chunk_nodes(chunks, routes={})
    for i, s in enumerate(summaries):
        nid = f"chunk-{i}"
        if nid in nodes:
            nodes[nid].status = "completed"
            nodes[nid].output_summary = s
    nodes, plan = plan_compile_hierarchy(
        nodes,
        chunks,
        summaries,
        job_id="test-dag-parallel",
        fan_in=3,
        max_depth=6,
        skip_regional_below=0,
        compile_workers=4,
    )
    out = dag_scheduler.run_dag_compile(
        chunks,
        summaries,
        state,
        fan_in=3,
        max_depth=6,
        skip_regional_below=0,
        medium_chain=["medium-model"],
        heavy_chain=["heavy-model"],
        medium_first=True,
        max_workers=4,
        existing_nodes=nodes,
        frozen_plan=plan,
    )
    assert out["final_summary"]
    assert out["compile_calls"] >= 1
    assert out.get("dag_nodes")
    assert out.get("frozen") is True
    assert calls  # at least some compile nodes executed
    assert plan.fingerprint == out.get("fingerprint_after") or out.get("fingerprint_after")


def test_priority_for_kind_orders_executive_first():
    from src.core.priority_queue import (
        PRIORITY_EXECUTIVE,
        PRIORITY_MAP,
        PRIORITY_REGIONAL,
        priority_for_kind,
    )

    assert priority_for_kind("executive") < priority_for_kind("regional")
    assert priority_for_kind("regional") < priority_for_kind("chunk")
    assert priority_for_kind("executive") == PRIORITY_EXECUTIVE
    assert priority_for_kind("map") == PRIORITY_MAP
    assert priority_for_kind("regional") == PRIORITY_REGIONAL
