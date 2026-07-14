"""
Throttled job progress writes.

UI still sees live updates; DB is not hit on every chunk completion.
Major milestones always flush immediately.
"""
from __future__ import annotations

import threading
import time
from typing import Dict, Optional, Tuple

from src.core.config import settings

_lock = threading.Lock()
# job_id → (last_flush_mono, pending_progress, pending_message, force_next)
_STATE: Dict[str, Tuple[float, float, str, bool]] = {}


def _min_interval_sec() -> float:
    return float(getattr(settings, "PROGRESS_WRITE_INTERVAL_SEC", 0.75) or 0.75)


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
