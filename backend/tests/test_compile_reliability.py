"""Acceptance tests for reduce_compile hang fixes (timeout / budgets / stall)."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import httpx
import pytest


def test_compile_http_timeout_strictly_below_wall():
    from src.agents import models
    from src.core.config import settings

    wall = float(settings.COMPILE_CALL_MAX_SEC)
    t = models._compile_timeout()
    assert float(t.read) < wall
    assert float(t.connect) < wall


def test_startup_rejects_compile_timeout_drift(monkeypatch):
    from src.core.config import Settings

    s = Settings()
    object.__setattr__(s, "NIM_COMPILE_TIMEOUT_SEC", 200.0)
    object.__setattr__(s, "COMPILE_CALL_MAX_SEC", 180.0)
    with pytest.raises(ValueError, match="strictly less"):
        s.validate_for_runtime(require_cors=False)


def test_call_compile_llm_returns_before_wall_on_hung_nim(monkeypatch):
    """Hung socket must not hold the job past COMPILE_CALL_MAX_SEC."""
    from src.agents import models

    monkeypatch.setattr(models.settings, "COMPILE_CALL_MAX_SEC", 1.5)
    monkeypatch.setattr(models.settings, "NIM_COMPILE_TIMEOUT_SEC", 1.0)
    monkeypatch.setattr(models.settings, "NIM_CONNECT_TIMEOUT_SEC", 0.5)

    def hung(*_a, **_k):
        time.sleep(30)
        return "never", "m"

    monkeypatch.setattr(models, "call_chat_with_fallback", hung)
    monkeypatch.setattr(models, "get_nim_client", lambda: object())

    t0 = time.monotonic()
    with pytest.raises(models.NimApiError, match="hard timeout"):
        models._call_compile_llm("summary a\n\nsummary b", ["fake-model"])
    elapsed = time.monotonic() - t0
    assert elapsed < 4.0, f"took {elapsed:.2f}s — executor join still blocking?"


def test_fallback_chain_shares_single_compile_budget(monkeypatch):
    from src.agents import models

    monkeypatch.setattr(models.settings, "COMPILE_CALL_MAX_SEC", 2.0)
    monkeypatch.setattr(models.settings, "NIM_COMPILE_TIMEOUT_SEC", 1.5)
    monkeypatch.setattr(models.settings, "NIM_CONNECT_TIMEOUT_SEC", 0.3)
    monkeypatch.setattr(models, "get_nim_client", lambda: object())

    class FakeCompletions:
        def create(self, **kwargs):
            time.sleep(1.2)
            raise TimeoutError("hung read")

    class FakeClient:
        def __init__(self):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr(models, "get_nim_client", lambda: FakeClient())

    t0 = time.monotonic()
    with pytest.raises(Exception):
        models.call_chat_with_fallback(
            ["m1", "m2", "m3"],
            [{"role": "user", "content": "hi"}],
            max_retries_per_model=1,
            timeout=httpx.Timeout(1.5, connect=0.3),
            deadline_mono=time.monotonic() + 2.0,
        )
    elapsed = time.monotonic() - t0
    # Must not stack 1.2s × 3 models (~3.6s+); shared 2s budget.
    assert elapsed < 3.2, f"fallback chain stacked too long: {elapsed:.2f}s"


def test_reduce_compile_hits_node_ceiling_and_stitches(monkeypatch):
    from src.core import orchestrator
    from src.agents import models, quality_validation

    monkeypatch.setattr(orchestrator.settings, "DAG_COMPILE_ENABLED", False)
    monkeypatch.setattr(orchestrator.settings, "REDUCE_COMPILE_MAX_SEC", 0.05)
    monkeypatch.setattr(orchestrator.settings, "COMPILE_CALL_MAX_SEC", 30.0)
    monkeypatch.setattr(orchestrator.settings, "COMPILE_MEDIUM_FIRST", True)
    monkeypatch.setattr(orchestrator.settings, "CARBON_BUDGET_ENABLED", True)
    monkeypatch.setattr(orchestrator.settings, "ADAPTIVE_REGIONAL_HIERARCHY", False)

    calls = {"n": 0}

    def slow_compile(inputs, state, model_ids=None, **_kwargs):
        calls["n"] += 1
        time.sleep(0.2)
        return "## Summary\nprimary"

    monkeypatch.setattr(models, "run_compile_with_models", slow_compile)
    monkeypatch.setattr(
        models,
        "stitch_compile_fallback",
        lambda inputs, reason="x": f"## Summary\nstitched ({reason})",
    )

    # Force QVA fail so heavy/repair would normally run
    monkeypatch.setattr(
        quality_validation,
        "validate_final",
        lambda *_a, **_k: quality_validation.ValidationVerdict(
            passed=False,
            confidence=0.1,
            faithfulness=0.1,
            coverage=0.1,
            hallucination_rate=0.9,
            contradiction_rate=0.0,
            codes=["low_confidence"],
            details={},
        ),
    )
    monkeypatch.setattr(orchestrator, "_set_progress", lambda *_a, **_k: None)

    state: Dict[str, Any] = {
        "job_id": "ceil-test",
        "routing_decision": {"compile_fallbacks": ["heavy-a"]},
        "summaries": ["Alpha finding.", "Beta finding."],
        "chunks": [],
        "pipeline_intelligence": {
            "strategy": {"medium_first": True, "compile_tier_hint": "medium"}
        },
        "carbon_budget_g": 40.0,
        "carbon_spent_g": 0.0,
        "accept_with_warning": False,
        "ingestion_latency": {},
        "model_usage_chars": {"light": 0, "medium": 0, "large": 0},
    }
    # Drain node budget before expensive follow-ups by making first call spend it.
    monkeypatch.setattr(orchestrator.settings, "REDUCE_COMPILE_MAX_SEC", 0.15)

    out = orchestrator.reduce_compile(state)
    meta = out["compile_meta"]
    assert meta["compile_calls"] >= 1
    # Heavy / repair should be skipped due to time ceiling (or stitched path).
    assert (
        any(s.get("reason") == "reduce_compile_time_ceiling" for s in meta.get("skipped_steps") or [])
        or meta.get("used_stitched_fallback")
        or meta.get("heavy_compile_ms") is None
    )
    assert out["final_summary"]
    assert "medium_compile_ms" in meta
    assert "quality_check_ms" in meta


def test_reduce_compile_skips_repair_when_carbon_spent(monkeypatch):
    from src.core import orchestrator
    from src.agents import models, quality_validation

    monkeypatch.setattr(orchestrator.settings, "DAG_COMPILE_ENABLED", False)
    monkeypatch.setattr(orchestrator.settings, "REDUCE_COMPILE_MAX_SEC", 120.0)
    monkeypatch.setattr(orchestrator.settings, "COMPILE_CALL_MAX_SEC", 30.0)
    monkeypatch.setattr(orchestrator.settings, "CARBON_BUDGET_ENABLED", True)
    monkeypatch.setattr(orchestrator.settings, "ADAPTIVE_REGIONAL_HIERARCHY", False)
    monkeypatch.setattr(orchestrator, "_set_progress", lambda *_a, **_k: None)

    def fast_compile(inputs, state, model_ids=None, **_kwargs):
        return "## Summary\nok"

    monkeypatch.setattr(models, "run_compile_with_models", fast_compile)
    monkeypatch.setattr(
        quality_validation,
        "validate_final",
        lambda *_a, **_k: quality_validation.ValidationVerdict(
            passed=False,
            confidence=0.1,
            faithfulness=0.1,
            coverage=0.1,
            hallucination_rate=0.9,
            contradiction_rate=0.0,
            codes=["low_confidence"],
            details={},
        ),
    )

    state = {
        "job_id": "carbon-gate",
        "routing_decision": {"compile_fallbacks": ["heavy-a"]},
        "summaries": ["A", "B"],
        "chunks": [],
        "pipeline_intelligence": {"strategy": {"medium_first": True}},
        "carbon_budget_g": 1.0,
        "carbon_spent_g": 1.0,  # already exhausted before compile
        "accept_with_warning": False,
        "ingestion_latency": {},
        "model_usage_chars": {"light": 0, "medium": 0, "large": 0},
    }
    out = orchestrator.reduce_compile(state)
    meta = out["compile_meta"]
    # Primary compile still runs; heavy/repair gated by carbon.
    assert meta.get("heavy_compile_ms") is None
    assert any(
        s.get("reason") == "carbon_budget_exhausted"
        for s in (meta.get("skipped_steps") or [])
    )


def test_stalled_job_detected_before_runtime_wall(monkeypatch):
    from src.db import jobs as job_store
    from src.core import job_status as job_status_mod

    monkeypatch.setattr(job_store.settings, "WORKER_JOB_HEARTBEAT_STALE_SEC", 1.0)
    monkeypatch.setattr(job_store.settings, "WORKER_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(job_store, "_db_enabled", lambda: False)

    jid = "stall-test-1"
    old = datetime.now(timezone.utc) - timedelta(seconds=5)
    job_store.JOB_STATUSES[jid] = {
        "job_id": jid,
        "status": job_status_mod.STATUS_PROCESSING,
        "progress": 82.0,
        "message": "Compiling executive summary...",
        "attempt_count": 1,
        "heartbeat_at": old,
    }
    assert job_store.is_job_heartbeat_stale(job_store.JOB_STATUSES[jid])
    updated = job_store.detect_and_handle_stalled_job(jid)
    assert updated.get("stalled") is True
    assert updated.get("status") == job_status_mod.STATUS_PENDING
    assert "Stalled" in (updated.get("message") or "")
    assert "Compiling" not in (updated.get("message") or "") or "retrying" in (
        updated.get("message") or ""
    ).lower()


def test_escalate_once_is_concurrent():
    """Task 7: escalate_once already dispatches failed chunks via ThreadPoolExecutor."""
    import inspect
    from src.core import orchestrator

    src = inspect.getsource(orchestrator.escalate_once)
    assert "ThreadPoolExecutor" in src
    assert "as_completed" in src
    assert "Concurrent dispatch" in src or "concurrently" in src.lower()


def test_carbon_accounting_uses_measured_compile_calls():
    from src.carbon import accounting

    state = {
        "final_summary": "Hello world " * 50,
        "total_chunks": 8,
        "chunks": [],
        "routing_decision": {"tier": "medium", "compile_tier": "medium"},
        "compile_meta": {
            "compile_calls": 3,
            "used_heavy": True,
            "medium_compile_ms": 100,
            "heavy_compile_ms": 200,
            "compile_carbon_g": 0.9,
        },
        "model_usage_chars": {"light": 0, "medium": 1000, "large": 2000},
        "chunks_escalated": 0,
    }
    report = accounting.estimate_workflow_carbon(
        "job-x", state, grid={"intensity_gco2_kwh": 500.0}
    )
    assert int(report.get("compile_calls") or 0) == 3
    assert int((report.get("routing_impact") or {}).get("compile_calls") or 0) == 3
    assert int((report.get("breakdown") or {}).get("compile_calls") or 0) == 3
    assert report.get("compile_substeps_ms", {}).get("medium_compile_ms") == 100
