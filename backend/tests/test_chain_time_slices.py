"""
Task 5: primary hang must not starve fallback — map + compile chains.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

import pytest


def test_allocate_slices_guarantees_last_fallback():
    from src.core.chain_time_budget import allocate_slices

    slices = allocate_slices(3, 90.0, [0.40, 0.35, 0.25], min_slice_sec=8.0)
    assert len(slices) == 3
    assert abs(sum(slices) - 90.0) < 0.05
    assert slices[-1] >= 8.0
    # Primary must not get the whole wall
    assert slices[0] < 90.0 * 0.7


def test_map_chain_primary_hang_invokes_fallback(monkeypatch):
    """Primary sleeps past its slice; fallback must run and succeed within wall."""
    from src.agents import models
    from src.core import chain_time_budget as ctb

    monkeypatch.setattr(models.settings, "CHAIN_SLICE_ENABLED", True)
    monkeypatch.setattr(models.settings, "MAP_CHAIN_SLICE_FRACTIONS", "0.40,0.60")
    monkeypatch.setattr(models.settings, "CHAIN_SLICE_MIN_SEC", 0.4)
    monkeypatch.setattr(models.settings, "NIM_ENDPOINT_POOL_ENABLED", False)
    monkeypatch.setattr(models.settings, "LLM_PROVIDER", "openai_compatible")
    monkeypatch.setattr(models.settings, "NIM_TRANSIENT_RETRIES", 1)
    monkeypatch.setattr(models.settings, "NIM_ENDPOINT_RETRIES_PER_MODEL", 1)
    monkeypatch.setattr(models.settings, "MODEL_RELIABILITY_SOFT_DEPRIORITIZE", False)
    ctb.reset_reliability_tracker_for_tests()

    calls: List[str] = []

    def fake_unsliced(model_ids, messages, **kwargs):
        mid = model_ids[0]
        calls.append(mid)
        deadline = kwargs.get("deadline_mono")
        # Simulate primary hanging past any reasonable slice
        if mid == "primary-hang":
            time.sleep(5.0)
            return "late-primary", mid
        return f"ok-from-{mid}", mid

    monkeypatch.setattr(models, "_call_chat_with_fallback_unsliced", fake_unsliced)

    wall = 1.5
    deadline = time.monotonic() + wall
    meta: Dict[str, Any] = {"phase": "map", "endpoint_role": "map"}
    t0 = time.monotonic()
    text, used = models.call_chat_with_fallback(
        ["primary-hang", "fallback-fast"],
        [{"role": "user", "content": "x"}],
        deadline_mono=deadline,
        call_meta=meta,
        max_retries_per_model=1,
    )
    elapsed = time.monotonic() - t0

    assert "fallback-fast" in calls, f"fallback never invoked; calls={calls}"
    assert used == "fallback-fast"
    assert "ok-from-fallback" in text
    assert elapsed < wall + 1.0, f"elapsed {elapsed:.2f}s exceeded wall {wall}s"
    # Slice report must show primary cut at slice, not full wall
    report = meta.get("chain_slices") or {}
    attempts = report.get("attempts") or []
    assert attempts, report
    primary = attempts[0]
    assert primary["outcome"] == "timeout_slice"
    assert primary["used_sec"] < wall * 0.85
    assert attempts[1]["outcome"] == "success"


def test_compile_chain_primary_hang_invokes_fallback(monkeypatch):
    """Compile path (hedge off): sliced sequential chain still reaches fallback."""
    from src.agents import models
    from src.core import chain_time_budget as ctb

    monkeypatch.setattr(models.settings, "CHAIN_SLICE_ENABLED", True)
    monkeypatch.setattr(models.settings, "COMPILE_HEDGED_FALLBACK_ENABLED", False)
    monkeypatch.setattr(models.settings, "COMPILE_CHAIN_SLICE_FRACTIONS", "0.35,0.65")
    monkeypatch.setattr(models.settings, "CHAIN_SLICE_MIN_SEC", 0.35)
    monkeypatch.setattr(models.settings, "COMPILE_CALL_MAX_SEC", 1.6)
    monkeypatch.setattr(models.settings, "NIM_COMPILE_TIMEOUT_SEC", 1.0)
    monkeypatch.setattr(models.settings, "MODEL_RELIABILITY_SOFT_DEPRIORITIZE", False)
    ctb.reset_reliability_tracker_for_tests()

    calls: List[str] = []

    def fake_unsliced(model_ids, messages, **kwargs):
        mid = model_ids[0]
        calls.append(mid)
        if mid == "compile-primary":
            time.sleep(5.0)
            return "late", mid
        return "executive-ok", mid

    monkeypatch.setattr(models, "_call_chat_with_fallback_unsliced", fake_unsliced)

    meta: Dict[str, Any] = {"phase": "compile", "endpoint_role": "compile"}
    wall = 1.6
    deadline = time.monotonic() + wall
    t0 = time.monotonic()
    text, used = models.call_chat_with_fallback(
        ["compile-primary", "compile-fallback"],
        [{"role": "user", "content": "summaries"}],
        deadline_mono=deadline,
        call_meta=meta,
        max_retries_per_model=1,
    )
    elapsed = time.monotonic() - t0

    assert "compile-fallback" in calls
    assert used == "compile-fallback"
    assert text == "executive-ok"
    assert elapsed < wall + 1.0
    attempts = (meta.get("chain_slices") or {}).get("attempts") or []
    assert attempts[0]["outcome"] == "timeout_slice"
    assert attempts[1]["outcome"] == "success"


def test_compile_hedged_fallback_fires_concurrently(monkeypatch):
    from src.agents import models
    from src.core import chain_time_budget as ctb

    monkeypatch.setattr(models.settings, "COMPILE_HEDGED_FALLBACK_ENABLED", True)
    monkeypatch.setattr(models.settings, "CHAIN_SLICE_ENABLED", True)
    monkeypatch.setattr(models.settings, "COMPILE_CHAIN_SLICE_FRACTIONS", "0.40,0.60")
    monkeypatch.setattr(models.settings, "CHAIN_SLICE_MIN_SEC", 0.3)
    monkeypatch.setattr(models.settings, "COMPILE_CALL_MAX_SEC", 2.0)
    monkeypatch.setattr(models.settings, "NIM_COMPILE_TIMEOUT_SEC", 1.5)
    monkeypatch.setattr(models.settings, "MODEL_RELIABILITY_SOFT_DEPRIORITIZE", False)
    ctb.reset_reliability_tracker_for_tests()

    started: Dict[str, float] = {}
    released = {"fallback": False}

    def fake_chat(model_ids, messages, **kwargs):
        mid = model_ids[0]
        started[mid] = time.monotonic()
        if mid == "p1":
            time.sleep(3.0)
            return "from-p1", mid
        # Fallback is fast
        time.sleep(0.15)
        released["fallback"] = True
        return "from-fb", mid

    monkeypatch.setattr(models, "call_chat_with_fallback", fake_chat)

    t0 = time.monotonic()
    text, used = models._call_compile_llm(
        "chunk a\n\nchunk b",
        ["p1", "fb1"],
        deadline_mono=time.monotonic() + 2.0,
    )
    elapsed = time.monotonic() - t0

    assert text == "from-fb"
    assert used == "fb1"
    assert released["fallback"] is True
    # Hedge should finish well under waiting for primary's full 3s hang
    assert elapsed < 1.8, f"hedge too slow: {elapsed:.2f}s"
    assert "p1" in started and "fb1" in started


def test_reliability_tracker_soft_deprioritize_requires_evidence():
    from src.core.chain_time_budget import ModelReliabilityTracker

    tr = ModelReliabilityTracker(window=30)
    # One job worth of timeouts — must NOT demote
    for _ in range(3):
        tr.record("flaky", ok=False, timeout=True)
    ordered = tr.soft_deprioritize_order(
        ["flaky", "stable"],
        enabled=True,
        timeout_rate_threshold=0.55,
        min_samples=20,
    )
    assert ordered[0] == "flaky"

    for _ in range(20):
        tr.record("flaky", ok=False, timeout=True)
    ordered2 = tr.soft_deprioritize_order(
        ["flaky", "stable"],
        enabled=True,
        timeout_rate_threshold=0.55,
        min_samples=20,
    )
    assert ordered2[0] == "stable"
    assert ordered2[1] == "flaky"
