"""
Throttled job progress writes + compile-cycle lifecycle precedence.

UI still sees live updates; DB is not hit on every chunk completion.
Major milestones always flush immediately.

Compile lifecycle is scoped to a ``compile_cycle_id`` (generation counter):

    Planning → Trying → Completed   (one cycle)

Each legitimate compile pass starts a new cycle via Planning. Stale writers
from older cycles cannot overwrite the active cycle. Scheduler telemetry
(ETA / workers) never replaces lifecycle messages while a cycle is active.
"""
from __future__ import annotations

import re
import threading
import time
from typing import Any, Dict, Optional, Tuple

from src.core.config import settings

_lock = threading.Lock()
# job_id → (last_flush_mono, pending_progress, pending_message, force_next)
_STATE: Dict[str, Tuple[float, float, str, bool]] = {}

# Serialize lifecycle reads/writes across hedge threads + scheduler callbacks.
_lifecycle_lock = threading.Lock()
# job_id → {cycle_id, ordinal, message}
_LIFECYCLE: Dict[str, Dict[str, Any]] = {}

_PHASE_ORDINAL = {"Planning": 1, "Trying": 2, "Completed": 3}

# Scheduler / DAG telemetry that must never replace lifecycle lines.
_SCHEDULER_TELEMETRY_RE = re.compile(
    r"(·\s*ETA\b|\bETA\s+\d|\bworkers\s+\d+/\d+|:\s*\d+/\d+\s*·)",
    re.IGNORECASE,
)
_LIFECYCLE_MSG_RE = re.compile(
    r"·\s*(Planning|Trying|Completed)\s*:",
    re.IGNORECASE,
)
_POST_COMPILE_MILESTONE_RE = re.compile(
    r"(Summary Ready|Indexing for search|Recording metrics|Search Ready|"
    r"Unified pipeline DAG complete|Background)",
    re.IGNORECASE,
)


def _min_interval_sec() -> float:
    return float(getattr(settings, "PROGRESS_WRITE_INTERVAL_SEC", 0.75) or 0.75)


def _normalize_phase(phase: str) -> str:
    phase_key = (phase or "Trying").strip().capitalize()
    if phase_key not in _PHASE_ORDINAL:
        return "Trying"
    return phase_key


def is_scheduler_telemetry_message(message: str) -> bool:
    return bool(_SCHEDULER_TELEMETRY_RE.search(message or ""))


def is_lifecycle_message(message: str) -> bool:
    return bool(_LIFECYCLE_MSG_RE.search(message or ""))


def is_post_compile_milestone(message: str) -> bool:
    return bool(_POST_COMPILE_MILESTONE_RE.search(message or ""))


def _force_write_progress(job_id: str, progress: float, message: str) -> None:
    """Persist progress without lifecycle retain (caller already holds policy)."""
    from src.db import jobs as job_store
    from src.core import job_status as job_status_mod

    current = job_store.JOB_STATUSES.get(job_id) or {}
    status = current.get("status") or job_status_mod.STATUS_PROCESSING
    if str(status) in (
        job_status_mod.STATUS_COMPLETE,
        job_status_mod.STATUS_ERROR,
        job_status_mod.STATUS_CANCELLED,
    ):
        return
    job_store.JOB_STATUSES[job_id] = {
        **current,
        "job_id": job_id,
        "status": status,
        "progress": float(progress),
        "message": message,
    }
    job_store.upsert_job(
        job_id,
        progress=float(progress),
        message=message,
        status=status,
    )


def publish_lifecycle_progress(
    job_id: str,
    *,
    phase: str,
    message: str,
    progress: float,
    cycle_id: Optional[int] = None,
    progress_gate: Any = None,
) -> Optional[int]:
    """
    Publish a compile lifecycle line under a lock.

    Returns the active ``compile_cycle_id`` if the write succeeded, else None.

    - ``Planning`` always starts a new cycle (increments generation).
    - ``Trying`` / ``Completed`` must pass the ``cycle_id`` from that Planning.
    - Within a cycle, phases are monotonic; Completed seals the cycle until
      the next Planning.
    - Writers with a stale ``cycle_id`` are rejected.
    """
    if not job_id:
        return None
    phase_key = _normalize_phase(phase)
    ordinal = _PHASE_ORDINAL[phase_key]

    with _lifecycle_lock:
        # Hedge winner seals the gate before Completed — block late Trying
        # from losers in the *same* cycle without relying on timing.
        if phase_key != "Completed" and progress_gate is not None:
            try:
                if progress_gate.is_set():
                    return None
            except Exception:
                pass

        cur = _LIFECYCLE.get(job_id)

        if phase_key == "Planning":
            new_cycle = int(cur.get("cycle_id") or 0) + 1 if cur else 1
            _LIFECYCLE[job_id] = {
                "cycle_id": new_cycle,
                "ordinal": ordinal,
                "message": message,
            }
            _force_write_progress(job_id, float(progress), message)
            return new_cycle

        # Trying / Completed require a matching active cycle.
        if cycle_id is None:
            return None
        if not cur:
            return None
        active = int(cur.get("cycle_id") or 0)
        if int(cycle_id) != active:
            # Stale writer from an older (or future) compile cycle.
            return None
        cur_ord = int(cur.get("ordinal") or 0)
        if ordinal < cur_ord:
            return None
        # Completed seals this cycle: further Trying is rejected until Planning.
        if cur_ord >= _PHASE_ORDINAL["Completed"] and phase_key != "Completed":
            return None

        _LIFECYCLE[job_id] = {
            "cycle_id": active,
            "ordinal": ordinal,
            "message": message,
        }
        _force_write_progress(job_id, float(progress), message)

        if phase_key == "Completed" and progress_gate is not None:
            try:
                progress_gate.set()
            except Exception:
                pass
        return active


def resolve_progress_message(job_id: str, incoming: str) -> str:
    """
    Apply lifecycle precedence for non-lifecycle writers (scheduler / ETA).

    Called under no caller lock; takes ``_lifecycle_lock`` internally.
    """
    with _lifecycle_lock:
        cur = _LIFECYCLE.get(job_id)
        if not cur:
            return incoming
        lifecycle_msg = str(cur.get("message") or "")
        if not lifecycle_msg:
            return incoming

        if is_scheduler_telemetry_message(incoming):
            return lifecycle_msg

        # Stale lifecycle-shaped lines via set_progress (no cycle_id) cannot
        # regress the visible message while a cycle is active.
        if is_lifecycle_message(incoming):
            return lifecycle_msg

        if is_post_compile_milestone(incoming):
            _LIFECYCLE.pop(job_id, None)
            return incoming

        # Active cycle: keep lifecycle over generic scheduler text.
        if is_lifecycle_message(lifecycle_msg):
            return lifecycle_msg

        return incoming


def set_progress_throttled(
    job_id: str,
    progress: float,
    message: str,
    *,
    force: bool = False,
) -> None:
    """
    Update in-memory progress always; persist to DB at most every
    PROGRESS_WRITE_INTERVAL_SEC unless ``force`` (milestones / terminal).
    """
    from src.db import jobs as job_store
    from src.core import job_status as job_status_mod

    message = resolve_progress_message(job_id, message)

    # Always keep process-local cache hot for same-process readers
    current = job_store.JOB_STATUSES.get(job_id) or {}
    status = current.get("status") or job_status_mod.STATUS_PROCESSING
    if str(status) in (
        job_status_mod.STATUS_COMPLETE,
        job_status_mod.STATUS_ERROR,
        job_status_mod.STATUS_CANCELLED,
    ):
        return

    job_store.JOB_STATUSES[job_id] = {
        **current,
        "job_id": job_id,
        "status": status,
        "progress": float(progress),
        "message": message,
    }

    now = time.monotonic()
    interval = _min_interval_sec()
    with _lock:
        last, _, _, _ = _STATE.get(job_id, (0.0, 0.0, "", False))
        due = force or (now - last) >= interval
        if not due:
            _STATE[job_id] = (last, float(progress), message, False)
            return
        _STATE[job_id] = (now, float(progress), message, False)

    job_store.upsert_job(
        job_id,
        progress=float(progress),
        message=message,
        status=status,
    )


def flush_progress(job_id: str) -> None:
    """Force-persist any pending throttled progress for job_id."""
    from src.db import jobs as job_store
    from src.core import job_status as job_status_mod

    with _lock:
        entry = _STATE.get(job_id)
        if not entry:
            return
        _, progress, message, _ = entry
        _STATE[job_id] = (time.monotonic(), progress, message, False)

    message = resolve_progress_message(job_id, message)
    current = job_store.JOB_STATUSES.get(job_id) or {}
    status = current.get("status") or job_status_mod.STATUS_PROCESSING
    if str(status) in (
        job_status_mod.STATUS_COMPLETE,
        job_status_mod.STATUS_ERROR,
        job_status_mod.STATUS_CANCELLED,
    ):
        return
    job_store.upsert_job(
        job_id,
        progress=float(progress),
        message=message,
        status=status,
    )


def clear_progress_state(job_id: Optional[str] = None) -> None:
    with _lock:
        if job_id is None:
            _STATE.clear()
        else:
            _STATE.pop(job_id, None)
    with _lifecycle_lock:
        if job_id is None:
            _LIFECYCLE.clear()
        else:
            _LIFECYCLE.pop(job_id, None)
