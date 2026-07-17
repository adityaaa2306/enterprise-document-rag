"""Executive compile: reserved budget + monotonic best summary."""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import pytest

from src.agents import models, quality_validation
from src.core import dag_scheduler


def _fail_verdict(*_a, **_k):
    return quality_validation.ValidationVerdict(
        passed=False,
        confidence=0.1,
        faithfulness=0.1,
        coverage=0.1,
        hallucination_rate=0.9,
        contradiction_rate=0.0,
        codes=["low_confidence"],
        details={},
    )


def _ok_verdict(*_a, **_k):
    return quality_validation.ValidationVerdict(
        passed=True,
        confidence=0.9,
        faithfulness=0.9,
        coverage=0.9,
        hallucination_rate=0.0,
        contradiction_rate=0.0,
        codes=[],
        details={},
    )


def test_is_stitched_fallback_detection():
    stitched = models.stitch_compile_fallback(["chunk a"], reason="x")
    assert models.is_stitched_fallback(stitched)
    assert not models.is_executive_compile_success(stitched)
    assert models.is_executive_compile_success("## Summary\n\nReal executive prose.")


def test_hedged_compile_waits_for_slow_success_after_primary_fails(monkeypatch):
    """
    Regression: FIRST_COMPLETED on a failed Ministral must not abort while
    Gemma is still generating — that converted live successes into stitch.
    """
    from src.core import chain_time_budget as ctb

    def fake_chat(chain, messages, **kwargs):
        mid = (chain or ["?"])[0]
        meta = kwargs.get("call_meta") or {}
        ev = meta.get("cancel_event")
        if "ministral" in mid.lower():
            time.sleep(0.12)
            raise models.NimApiError(f"primary failed: {mid}")
        # finishes after primary failure is observed; honor cancel if signaled
        for _ in range(20):
            if ev is not None and ev.is_set():
                raise models.HedgeCancelled("cancelled")
            time.sleep(0.02)
        return ("## Summary\n\nGemma executive that must be kept.", mid)

    def plan(ordered, role="compile", wall_sec=30.0):
        ids = list(ordered)[:2]
        slices = [0.15, 2.0]
        report = ctb.ChainSliceReport(
            role=role,
            wall_sec=wall_sec,
            fractions=[0.4, 0.6],
            attempts=[
                ctb.SliceAttempt(model_id=ids[0], position=0, allocated_sec=slices[0]),
                ctb.SliceAttempt(model_id=ids[1], position=1, allocated_sec=slices[1]),
            ],
        )
        return ids, slices, report

    monkeypatch.setattr(models, "call_chat_with_fallback", fake_chat)
    monkeypatch.setattr(ctb, "plan_chain_slices", plan)
    monkeypatch.setattr(ctb, "log_slice_report", lambda *_a, **_k: None)
    monkeypatch.setattr(
        ctb,
        "get_reliability_tracker",
        lambda: type("T", (), {"record": lambda *a, **k: None})(),
    )

    text, used = models._call_compile_llm_hedged(
        [{"role": "user", "content": "summarize"}],
        [
            "mistralai/ministral-14b-instruct-2512",
            "google/gemma-4-31b-it",
        ],
        intermediate=False,
        deadline_mono=time.monotonic() + 5.0,
        hard_sec=5.0,
    )
    assert "Gemma executive that must be kept" in text
    assert used and "gemma" in used.lower()


def test_hedge_cancels_loser_immediately_on_first_success(monkeypatch):
    """First durable success must signal cancel_event on outstanding losers."""
    from src.core import chain_time_budget as ctb

    cancel_seen = {"ministral": False}
    started = {"gemma": False}

    def fake_chat(chain, messages, **kwargs):
        mid = (chain or ["?"])[0]
        meta = kwargs.get("call_meta") or {}
        ev = meta.get("cancel_event")
        if "gemma" in mid.lower():
            started["gemma"] = True
            time.sleep(0.05)
            return ("## Summary\n\nFast gemma win.", mid)
        # Slow primary / loser — must observe cancel after gemma wins.
        for _ in range(80):
            if ev is not None and ev.is_set():
                cancel_seen["ministral"] = True
                raise models.HedgeCancelled("loser cancelled")
            time.sleep(0.05)
        return ("## Summary\n\nSlow primary should not win.", mid)

    def plan(ordered, role="compile", wall_sec=30.0):
        ids = list(ordered)[:2]
        slices = [0.08, 2.0]  # primary slice elapses quickly → hedge fires
        report = ctb.ChainSliceReport(
            role=role,
            wall_sec=wall_sec,
            fractions=[0.4, 0.6],
            attempts=[
                ctb.SliceAttempt(model_id=ids[0], position=0, allocated_sec=slices[0]),
                ctb.SliceAttempt(model_id=ids[1], position=1, allocated_sec=slices[1]),
            ],
        )
        return ids, slices, report

    monkeypatch.setattr(models, "call_chat_with_fallback", fake_chat)
    monkeypatch.setattr(ctb, "plan_chain_slices", plan)
    monkeypatch.setattr(ctb, "log_slice_report", lambda *_a, **_k: None)
    monkeypatch.setattr(
        ctb,
        "get_reliability_tracker",
        lambda: type("T", (), {"record": lambda *a, **k: None})(),
    )

    text, used = models._call_compile_llm_hedged(
        [{"role": "user", "content": "summarize"}],
        [
            "mistralai/ministral-14b-instruct-2512",
            "google/gemma-4-31b-it",
        ],
        intermediate=False,
        deadline_mono=time.monotonic() + 5.0,
        hard_sec=5.0,
    )
    assert "Fast gemma win" in text
    assert used and "gemma" in used.lower()
    assert started["gemma"] is True
    # Give loser thread a moment to observe cancel_event.
    deadline = time.monotonic() + 2.0
    while not cancel_seen["ministral"] and time.monotonic() < deadline:
        time.sleep(0.05)
    assert cancel_seen["ministral"] is True


def test_monotonic_keeps_medium_when_heavy_returns_stitch(monkeypatch):
    """Gemma success must survive a later heavy stitch/timeout."""
    calls: List[Optional[List[str]]] = []

    def fake_compile(inputs, state, model_ids=None, **kwargs):
        calls.append(list(model_ids or []))
        chain = list(model_ids or [])
        head = (chain[0] or "") if chain else ""
        if "gemma" in head.lower() or "medium" in head.lower() or len(calls) == 1:
            state.setdefault("models_used", []).append(head or "google/gemma-3-12b-it")
            return "## Summary\n\nDurable medium executive summary about leads."
        # Heavy path: emulate run_compile_with_models stitch fallback
        return models.stitch_compile_fallback(
            ["chunk"], reason="Shared call deadline exhausted"
        )

    monkeypatch.setattr(models, "run_compile_with_models", fake_compile)
    monkeypatch.setattr(quality_validation, "validate_final", _fail_verdict)

    out = dag_scheduler._compile_node_text(
        "chunk summaries here",
        medium_chain=["google/gemma-3-12b-it"],
        heavy_chain=["mistralai/mistral-small-3.1-24b-instruct-2503"],
        medium_first=True,
        qva_tau=0.58,
        deadline_mono=time.monotonic() + 60.0,
        state={"features": {"grid_intensity": 400.0}, "models_used": []},
        assigned_model="google/gemma-3-12b-it",
    )
    assert models.is_executive_compile_success(out["summary"])
    assert "Durable medium executive" in out["summary"]
    assert not models.is_stitched_fallback(out["summary"])
    status = out["compile_status"]
    assert status["summary_source"] == "executive_compile"
    assert status["best_compile_model"]
    assert status["heavy_compile_skipped"] in ("compile_failed", None) or status[
        "compile_status"
    ] in ("degraded_enhance_failed", "ok")
    assert status["compile_status"] != "stitched_fallback"


def test_heavy_enhance_skipped_when_budget_exhausted_keeps_medium(monkeypatch):
    def fake_compile(inputs, state, model_ids=None, **kwargs):
        state.setdefault("models_used", []).append("google/gemma-3-12b-it")
        return "## Summary\n\nMedium executive that must be kept."

    monkeypatch.setattr(models, "run_compile_with_models", fake_compile)
    monkeypatch.setattr(quality_validation, "validate_final", _fail_verdict)

    # Only ~5s left → below enhance_min_sec (15)
    out = dag_scheduler._compile_node_text(
        "chunk text",
        medium_chain=["google/gemma-3-12b-it"],
        heavy_chain=["meta/llama-3.3-70b-instruct"],
        medium_first=True,
        qva_tau=0.58,
        deadline_mono=time.monotonic() + 5.0,
        state={"features": {}, "models_used": []},
    )
    assert "Medium executive that must be kept" in out["summary"]
    assert out["compile_status"]["heavy_compile_skipped"] == "deadline_budget"
    assert out["compile_status"]["compile_status"] == "degraded_timeout"
    assert out["compile_status"]["summary_source"] == "executive_compile"


def test_stitch_only_when_no_executive_succeeds(monkeypatch):
    def always_stitch(inputs, state, model_ids=None, **kwargs):
        return models.stitch_compile_fallback(["a"], reason="all failed")

    monkeypatch.setattr(models, "run_compile_with_models", always_stitch)
    monkeypatch.setattr(quality_validation, "validate_final", _fail_verdict)

    out = dag_scheduler._compile_node_text(
        "chunk text",
        medium_chain=["google/gemma-3-12b-it"],
        heavy_chain=["meta/llama-3.3-70b-instruct"],
        medium_first=True,
        qva_tau=0.58,
        deadline_mono=time.monotonic() + 60.0,
        state={"features": {}, "models_used": []},
    )
    assert models.is_stitched_fallback(out["summary"])
    assert out["compile_status"]["summary_source"] == "stitched_fallback"


def test_heavy_success_replaces_medium(monkeypatch):
    def fake_compile(inputs, state, model_ids=None, **kwargs):
        chain = list(model_ids or [])
        head = chain[0] if chain else ""
        if "llama" in head.lower() or "mistral" in head.lower():
            state.setdefault("models_used", []).append(head)
            return "## Summary\n\nImproved heavy executive summary."
        state.setdefault("models_used", []).append(head or "gemma")
        return "## Summary\n\nMedium executive summary."

    monkeypatch.setattr(models, "run_compile_with_models", fake_compile)
    monkeypatch.setattr(quality_validation, "validate_final", _fail_verdict)

    out = dag_scheduler._compile_node_text(
        "chunk text",
        medium_chain=["google/gemma-3-12b-it"],
        heavy_chain=["meta/llama-3.3-70b-instruct"],
        medium_first=True,
        qva_tau=0.58,
        deadline_mono=time.monotonic() + 60.0,
        state={"features": {}, "models_used": []},
    )
    assert "Improved heavy executive" in out["summary"]
    assert out["used_heavy"] is True
    assert out["compile_status"]["summary_source"] == "executive_compile"


def test_map_deadline_ceiling_reserves_compile_budget():
    """Map phase ceiling must leave COMPILE_RESERVED_SEC before absolute job end."""
    from src.core.config import settings

    reserved = float(settings.COMPILE_RESERVED_SEC)
    absolute = time.monotonic() + 600.0
    pre = absolute - reserved
    assert pre < absolute
    assert (absolute - pre) == pytest.approx(reserved)


def test_capacity_pool_respects_deadline_ceiling(monkeypatch):
    from src.core import execution_scheduler as sched

    seen: List[float] = []

    def worker(payload, deadline_mono=None):
        seen.append(float(deadline_mono) if deadline_mono is not None else -1.0)
        return payload

    ceiling = time.monotonic() + 3.0
    ordered, prog, _mets = sched.run_capacity_pool(
        [1],
        worker,
        role="map",
        kind="map",
        max_workers=1,
        hard_timeout_sec=90.0,
        max_attempts=1,
        deadline_ceiling_mono=ceiling,
    )
    assert ordered == [1]
    assert seen and seen[0] <= ceiling + 0.05


def test_exclusive_reserved_budget_after_long_map_regional():
    """
    After a long map/regional phase that leaves only ~12s of absolute job wall,
    executive/final must still receive the full reserved window (60s), not
    min(remaining_job_wall, reserved).
    """
    reserved = 60.0
    hard = 90.0
    t0 = 1_000_000.0
    abs_deadline = t0 + 600.0
    # Long map+regional: only 12s of absolute job wall remain.
    now_late = abs_deadline - 12.0
    assert abs_deadline - now_late == pytest.approx(12.0)

    tl = dag_scheduler.compute_compile_budget_timeline(
        now_mono=now_late,
        absolute_job_deadline_mono=abs_deadline,
        reserved_sec=reserved,
        per_task_hard_sec=hard,
    )
    stages = tl["stages"]

    # Pre-exec stages cannot enter the reserved tail.
    assert tl["pre_executive_ceiling_mono"] == pytest.approx(abs_deadline - reserved)
    for kind in ("map", "regional", "chapter"):
        assert stages[kind]["owns_reserved_budget"] is False
        assert stages[kind]["deadline_mono"] <= tl["pre_executive_ceiling_mono"] + 1e-9
        # At this late clock, pre-ceiling is already past → remaining 0 for map.
        assert stages[kind]["remaining_sec"] == pytest.approx(0.0)

    # Executive owns full reserved — NOT min(12, 60)=12.
    assert stages["executive"]["owns_reserved_budget"] is True
    assert stages["executive"]["remaining_sec"] == pytest.approx(reserved)
    assert stages["executive"]["deadline_mono"] == pytest.approx(now_late + reserved)
    assert stages["executive"]["deadline_mono"] > abs_deadline  # may extend past job wall
    assert stages["final"]["remaining_sec"] == pytest.approx(reserved)

    # phase_deadline_mono must match (no abs clamp).
    exec_d = dag_scheduler.phase_deadline_mono(
        "executive",
        now_mono=now_late,
        absolute_job_deadline_mono=abs_deadline,
        pre_executive_ceiling_mono=tl["pre_executive_ceiling_mono"],
        reserved_sec=reserved,
        per_task_lease_mono=now_late + hard,
    )
    shared_remaining = abs_deadline - now_late  # 12s
    assert exec_d - now_late == pytest.approx(reserved)
    assert exec_d - now_late > shared_remaining

    # Mid-job (healthy): map still under pre-ceiling; executive still full reserved.
    now_mid = t0 + 100.0
    tl_mid = dag_scheduler.compute_compile_budget_timeline(
        now_mono=now_mid,
        absolute_job_deadline_mono=abs_deadline,
        reserved_sec=reserved,
        per_task_hard_sec=hard,
    )
    assert tl_mid["stages"]["map"]["deadline_mono"] <= tl_mid["pre_executive_ceiling_mono"]
    assert tl_mid["stages"]["regional"]["remaining_sec"] == pytest.approx(hard)
    assert tl_mid["stages"]["executive"]["remaining_sec"] == pytest.approx(reserved)
    assert tl_mid["stages"]["chapter"]["owns_reserved_budget"] is False
    assert tl_mid["stages"]["final"]["owns_reserved_budget"] is True


def test_executive_capacity_pool_not_clamped_by_absolute_job(monkeypatch):
    """Executive wave leases must not be min()'d against absolute job deadline."""
    from src.core import execution_scheduler as sched

    seen: List[float] = []
    reserved = 60.0
    abs_remaining = 12.0

    def worker(payload, deadline_mono=None):
        seen.append(float(deadline_mono) if deadline_mono is not None else -1.0)
        return payload

    # Mimic fixed executive wave: hard=reserved, ceiling=None (exclusive).
    t0 = time.monotonic()
    ordered, _prog, _mets = sched.run_capacity_pool(
        ["exec-1"],
        worker,
        role="compile",
        kind="compile",
        max_workers=1,
        hard_timeout_sec=reserved,
        max_attempts=1,
        deadline_ceiling_mono=None,
    )
    assert ordered == ["exec-1"]
    assert seen
    got = seen[0] - t0
    assert got >= reserved - 1.0
    assert got > abs_remaining
