"""
Job status helpers.

Canonical lifecycle (Phase 3 queue):
  pending → processing → complete | error | cancelled

API/legacy aliases: completed→complete, failed→error.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_COMPLETE = "complete"
STATUS_ERROR = "error"
STATUS_CANCELLED = "cancelled"

TERMINAL_STATUSES = frozenset({STATUS_COMPLETE, STATUS_ERROR, STATUS_CANCELLED})

_STATUS_ALIASES = {
    "completed": STATUS_COMPLETE,
    "done": STATUS_COMPLETE,
    "success": STATUS_COMPLETE,
    "ok": STATUS_COMPLETE,
    "failed": STATUS_ERROR,
    "failure": STATUS_ERROR,
    "canceled": STATUS_CANCELLED,
}


def normalize_job_status(raw: Optional[str]) -> str:
    """
    Normalize a job status string to a canonical value.

    Unknown values are returned lowercased (stripped); empty/None → ``pending``.
    """
    if raw is None:
        return STATUS_PENDING
    value = str(raw).strip().lower()
    if not value:
        return STATUS_PENDING
    return _STATUS_ALIASES.get(value, value)


def is_job_complete(raw: Optional[str]) -> bool:
    """True when status denotes successful completion (including aliases)."""
    return normalize_job_status(raw) == STATUS_COMPLETE


def is_terminal(raw: Optional[str]) -> bool:
    return normalize_job_status(raw) in TERMINAL_STATUSES


def is_job_ready_for_result(status_dict: Optional[Dict[str, Any]]) -> bool:
    """
    True when ``/job-result`` may return the SummaryResponse payload.

    Requires a ``result`` object with summary content. Prefer canonical
    ``complete`` status, but also accept a durable result when the status
    string lagged (stale in-memory pending/processing).
    """
    if not status_dict:
        return False
    result = status_dict.get("result")
    if not isinstance(result, dict):
        return False
    has_summary = bool(
        (result.get("final_summary") or "").strip()
        or result.get("summary_ready")
    )
    if not has_summary:
        return False
    if is_job_complete(status_dict.get("status")):
        return True
    # Lagging status with a real summary payload — still serve the result.
    return True
