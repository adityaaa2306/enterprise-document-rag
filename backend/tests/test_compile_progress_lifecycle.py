"""Live Job Status compile lifecycle: cycle-scoped, monotonic, scheduler-safe."""
from __future__ import annotations

import threading

import pytest

from src.perf import progress as prog


@pytest.fixture(autouse=True)
def _clear_progress(monkeypatch):
    prog.clear_progress_state()
    monkeypatch.setattr(prog, "_force_write_progress", lambda *_a, **_k: None)
    yield
    prog.clear_progress_state()


def test_lifecycle_order_planning_trying_completed(monkeypatch):
    writes = []
    monkeypatch.setattr(
        prog, "_force_write_progress", lambda j, p, m: writes.append(m)
    )

    cid = prog.publish_lifecycle_progress(
        "j1", phase="Planning", message="Executive Summary · Planning: Llama", progress=88.0
    )
    assert cid == 1
    assert prog.publish_lifecycle_progress(
        "j1",
        phase="Trying",
        message="Executive Summary · Trying: Llama",
        progress=88.0,
        cycle_id=cid,
    )
    assert prog.publish_lifecycle_progress(
        "j1",
        phase="Completed",
        message="Executive Summary · Completed: Llama",
        progress=89.0,
        cycle_id=cid,
    )
    assert writes == [
        "Executive Summary · Planning: Llama",
        "Executive Summary · Trying: Llama",
        "Executive Summary · Completed: Llama",
    ]


def test_completed_seals_cycle_but_planning_opens_new_cycle(monkeypatch):
    writes = []
    monkeypatch.setattr(
        prog, "_force_write_progress", lambda j, p, m: writes.append(m)
    )

    c1 = prog.publish_lifecycle_progress(
        "j1",
        phase="Planning",
        message="Executive Summary · Planning: Llama",
        progress=88.0,
    )
    prog.publish_lifecycle_progress(
        "j1",
        phase="Completed",
        message="Executive Summary · Completed: Llama",
        progress=89.0,
        cycle_id=c1,
    )
    # Same cycle: Trying rejected after Completed.
    assert (
        prog.publish_lifecycle_progress(
            "j1",
            phase="Trying",
            message="Executive Summary · Trying: Ministral",
            progress=88.0,
            cycle_id=c1,
        )
        is None
    )
    # New legitimate compile pass: Planning opens cycle 2.
    c2 = prog.publish_lifecycle_progress(
        "j1",
        phase="Planning",
        message="Executive Summary · Planning: Llama",
        progress=88.0,
    )
    assert c2 == 2
    assert prog.publish_lifecycle_progress(
        "j1",
        phase="Trying",
        message="Executive Summary · Trying: Llama",
        progress=88.0,
        cycle_id=c2,
    )
    assert "Executive Summary · Trying: Llama" in writes


def test_stale_cycle_writer_rejected_after_new_planning(monkeypatch):
    writes = []
    monkeypatch.setattr(
        prog, "_force_write_progress", lambda j, p, m: writes.append(m)
    )
    c1 = prog.publish_lifecycle_progress(
        "j1", phase="Planning", message="Executive Summary · Planning: A", progress=88.0
    )
    c2 = prog.publish_lifecycle_progress(
        "j1", phase="Planning", message="Executive Summary · Planning: B", progress=88.0
    )
    assert c1 == 1 and c2 == 2
    # Late Trying from cycle 1 must not overwrite cycle 2.
    assert (
        prog.publish_lifecycle_progress(
            "j1",
            phase="Trying",
            message="Executive Summary · Trying: stale",
            progress=88.0,
            cycle_id=c1,
        )
        is None
    )
    assert writes[-1] == "Executive Summary · Planning: B"


def test_progress_gate_blocks_trying_before_completed(monkeypatch):
    writes = []
    monkeypatch.setattr(
        prog, "_force_write_progress", lambda j, p, m: writes.append(m)
    )
    gate = threading.Event()
    cid = prog.publish_lifecycle_progress(
        "j1", phase="Planning", message="Executive Summary · Planning: Llama", progress=88.0
    )
    prog.publish_lifecycle_progress(
        "j1",
        phase="Trying",
        message="Executive Summary · Trying: Llama",
        progress=88.0,
        cycle_id=cid,
    )
    gate.set()  # hedge winner sealed
    assert (
        prog.publish_lifecycle_progress(
            "j1",
            phase="Trying",
            message="Executive Summary · Trying: Ministral",
            progress=88.0,
            cycle_id=cid,
            progress_gate=gate,
        )
        is None
    )
    assert prog.publish_lifecycle_progress(
        "j1",
        phase="Completed",
        message="Executive Summary · Completed: Llama",
        progress=89.0,
        cycle_id=cid,
        progress_gate=gate,
    )
    assert writes[-1] == "Executive Summary · Completed: Llama"


def test_scheduler_eta_cannot_overwrite_lifecycle():
    cid = prog.publish_lifecycle_progress(
        "j1",
        phase="Planning",
        message="Executive Summary · Planning: Ministral",
        progress=88.0,
    )
    prog.publish_lifecycle_progress(
        "j1",
        phase="Trying",
        message="Executive Summary · Trying: Ministral",
        progress=88.0,
        cycle_id=cid,
    )
    kept = prog.resolve_progress_message(
        "j1", "Executive Summary: 0/1 · ETA 2s · workers 1/6"
    )
    assert kept == "Executive Summary · Trying: Ministral"


def test_trying_cannot_overwrite_completed_via_resolve():
    cid = prog.publish_lifecycle_progress(
        "j1",
        phase="Planning",
        message="Executive Summary · Planning: Llama",
        progress=88.0,
    )
    prog.publish_lifecycle_progress(
        "j1",
        phase="Completed",
        message="Executive Summary · Completed: Llama",
        progress=89.0,
        cycle_id=cid,
    )
    kept = prog.resolve_progress_message(
        "j1", "Executive Summary · Trying: Ministral"
    )
    assert kept == "Executive Summary · Completed: Llama"


def test_intermediate_then_final_are_separate_cycles(monkeypatch):
    writes = []
    monkeypatch.setattr(
        prog, "_force_write_progress", lambda j, p, m: writes.append(m)
    )
    c1 = prog.publish_lifecycle_progress(
        "j1",
        phase="Planning",
        message="Compile · Planning: Llama",
        progress=85.0,
    )
    prog.publish_lifecycle_progress(
        "j1",
        phase="Completed",
        message="Compile · Completed: Llama",
        progress=85.0,
        cycle_id=c1,
    )
    c2 = prog.publish_lifecycle_progress(
        "j1",
        phase="Planning",
        message="Executive Summary · Planning: Llama",
        progress=88.0,
    )
    assert c2 == 2
    assert writes[-1] == "Executive Summary · Planning: Llama"


def test_summary_ready_allowed_after_completed():
    cid = prog.publish_lifecycle_progress(
        "j1",
        phase="Planning",
        message="Executive Summary · Planning: Llama",
        progress=88.0,
    )
    prog.publish_lifecycle_progress(
        "j1",
        phase="Completed",
        message="Executive Summary · Completed: Llama",
        progress=89.0,
        cycle_id=cid,
    )
    msg = prog.resolve_progress_message("j1", "Summary Ready")
    assert msg == "Summary Ready"


def test_trying_without_cycle_id_rejected():
    prog.publish_lifecycle_progress(
        "j1", phase="Planning", message="Executive Summary · Planning: A", progress=88.0
    )
    assert (
        prog.publish_lifecycle_progress(
            "j1",
            phase="Trying",
            message="Executive Summary · Trying: A",
            progress=88.0,
        )
        is None
    )
