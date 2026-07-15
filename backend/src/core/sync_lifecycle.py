"""
Lifecycle sync instrumentation — Summary Ready → Background → Frontend poll.

Logs every state transition so we can prove which hop is missing.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

log = logging.getLogger("sync.lifecycle")

_LAST_POLL_LOG: Dict[str, float] = {}


def log_transition(
    job_id: str,
    transition: str,
    *,
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    # Throttle high-frequency poll logs
    if transition == "Frontend Poll Received":
        now = time.time()
        prev = _LAST_POLL_LOG.get(job_id) or 0.0
        if now - prev < 2.0:
            return
        _LAST_POLL_LOG[job_id] = now
    payload = {
        "job_id": job_id,
        "transition": transition,
        "t": time.time(),
        **(detail or {}),
    }
    log.info("SYNC_LIFECYCLE %s", payload)


def metrics_ready_from_status(status_dict: Dict[str, Any]) -> bool:
    """
    True when background metrics are fully persisted and safe for UI cards.

    Summary Ready alone is NOT metrics-ready (carbon/region/chunks may still be zero).
    """
    bg = status_dict.get("background") if isinstance(status_dict.get("background"), dict) else {}
    phase = str(bg.get("phase") or "").lower()
    if phase in ("search_ready", "complete", "done"):
        return True
    msg = str(status_dict.get("message") or "").lower()
    if "search ready" in msg or "search available" in msg:
        return True
    # Result blob (when present) may already carry search_ready
    result = status_dict.get("result") if isinstance(status_dict.get("result"), dict) else {}
    rbg = result.get("background") if isinstance(result.get("background"), dict) else {}
    if str(rbg.get("phase") or "").lower() in ("search_ready", "complete", "done"):
        return True
    cd = result.get("carbon_data") if isinstance(result.get("carbon_data"), dict) else {}
    # Heuristic: modeled/region fields populated after finalize_metrics
    if (
        float(status_dict.get("progress") or 0) >= 100.0
        and (
            cd.get("region_decision")
            or cd.get("baseline_cost_gco2e")
            or cd.get("breakdown")
        )
    ):
        return True
    return False


def summary_ready_from_status(status_dict: Dict[str, Any]) -> bool:
    partial = status_dict.get("partial") if isinstance(status_dict.get("partial"), dict) else {}
    if partial.get("summary_ready"):
        return True
    result = status_dict.get("result") if isinstance(status_dict.get("result"), dict) else {}
    if result.get("summary_ready"):
        return True
    msg = str(status_dict.get("message") or "").lower()
    if "summary ready" in msg or "search ready" in msg or "search available" in msg:
        return True
    from src.core.job_status import is_job_complete

    if is_job_complete(status_dict.get("status")):
        return True
    return bool((result.get("final_summary") or "").strip())
