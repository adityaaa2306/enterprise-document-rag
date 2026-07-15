"""
Critical-path / post-DAG step timing (audit only — does not change behavior).

Usage:
    with CriticalPath(job_id).step("embed_prefetch_wait") as s:
        ...
    lat.add_meta(**cp.as_meta())
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

log = logging.getLogger(__name__)


class CriticalPath:
    def __init__(self, job_id: str, *, label: str = "post_dag"):
        self.job_id = job_id
        self.label = label
        self.steps: List[Dict[str, Any]] = []
        self._t0 = time.perf_counter()

    @contextmanager
    def step(self, name: str) -> Iterator[Dict[str, Any]]:
        start = time.perf_counter()
        wall_start = time.time()
        log.info(
            "Job %s: [critical-path] START %s/%s t=%.3f",
            self.job_id,
            self.label,
            name,
            wall_start,
        )
        info: Dict[str, Any] = {"name": name, "start_epoch": wall_start}
        try:
            yield info
        finally:
            end = time.perf_counter()
            wall_end = time.time()
            ms = round((end - start) * 1000.0, 2)
            info["end_epoch"] = wall_end
            info["ms"] = ms
            info["sec"] = round(ms / 1000.0, 3)
            self.steps.append(info)
            log.info(
                "Job %s: [critical-path] END %s/%s ms=%.1f sec=%.3f",
                self.job_id,
                self.label,
                name,
                ms,
                ms / 1000.0,
            )

    def total_ms(self) -> float:
        return round((time.perf_counter() - self._t0) * 1000.0, 2)

    def as_meta(self) -> Dict[str, Any]:
        return {
            f"{self.label}_steps": list(self.steps),
            f"{self.label}_total_ms": self.total_ms(),
            f"{self.label}_breakdown": {
                s["name"]: s["ms"] for s in self.steps
            },
        }

    def format_table(self) -> str:
        lines = [
            f"=== Critical path ({self.label}) job={self.job_id} ===",
            f"{'step':40} {'ms':>10} {'sec':>8}",
        ]
        for s in self.steps:
            lines.append(f"{s['name']:40} {s['ms']:10.1f} {s['sec']:8.3f}")
        lines.append(f"{'TOTAL':40} {self.total_ms():10.1f} {self.total_ms()/1000.0:8.3f}")
        return "\n".join(lines)


# Per-job DAG audit counters (process-local)
_DAG_AUDIT: Dict[str, Dict[str, Any]] = {}
_ACTIVE_JOB_ID: str = ""


def dag_audit_reset(job_id: str) -> None:
    global _ACTIVE_JOB_ID
    _ACTIVE_JOB_ID = job_id
    _DAG_AUDIT[job_id] = {
        "submit_counts": {},
        "deferred_overflow": [],
        "overflow_inserts": [],
        "ready_events": [],
        "node_count_history": [],
        "misleading_executive_msgs": 0,
        "compile_progress_stamps": [],
    }


def dag_audit_active_job() -> str:
    return _ACTIVE_JOB_ID or ""


def dag_audit_get(job_id: str) -> Dict[str, Any]:
    return _DAG_AUDIT.setdefault(job_id, {})


def dag_audit_record_submit(
    job_id: str,
    nid: str,
    *,
    kind: str,
    deps: List[str],
    dep_statuses: Dict[str, str],
    attempt: int,
) -> None:
    a = dag_audit_get(job_id)
    counts = a.setdefault("submit_counts", {})
    counts[nid] = int(counts.get(nid) or 0) + 1
    a.setdefault("ready_events", []).append(
        {
            "t": time.time(),
            "nid": nid,
            "kind": kind,
            "attempt": attempt,
            "submit_n": counts[nid],
            "deps": deps,
            "dep_statuses": dep_statuses,
        }
    )
    # Cap history
    if len(a["ready_events"]) > 500:
        a["ready_events"] = a["ready_events"][-250:]


def dag_audit_record_overflow(
    job_id: str,
    parent_id: str,
    new_ids: List[str],
    *,
    kind: str,
    nodes_total: int,
    regional_total: int,
) -> None:
    a = dag_audit_get(job_id)
    a.setdefault("overflow_inserts", []).append(
        {
            "t": time.time(),
            "parent_id": parent_id,
            "new_ids": list(new_ids),
            "kind": kind,
            "nodes_total": nodes_total,
            "regional_total": regional_total,
        }
    )


def dag_audit_record_node_counts(job_id: str, snap: Dict[str, Any], *, phase: str) -> None:
    a = dag_audit_get(job_id)
    a.setdefault("node_count_history", []).append(
        {
            "t": time.time(),
            "phase": phase,
            "total": snap.get("total"),
            "by_kind": dict(snap.get("by_kind") or {}),
            "overflow": dict(snap.get("overflow") or {}),
            "baseline": dict(snap.get("baseline") or {}),
        }
    )
    hist = a["node_count_history"]
    if len(hist) > 200:
        a["node_count_history"] = hist[-100:]


def dag_audit_record_wait(
    job_id: str,
    *,
    nid: str,
    kind: str,
    wait_sec: float,
    reason: str,
    unfinished_deps: Optional[List[str]] = None,
) -> None:
    """Record dependency / queue waits > 2s with an explanation."""
    if wait_sec < 2.0:
        return
    a = dag_audit_get(job_id)
    a.setdefault("waits_gt_2s", []).append(
        {
            "t": time.time(),
            "nid": nid,
            "kind": kind,
            "wait_sec": round(wait_sec, 3),
            "reason": reason,
            "unfinished_deps": list(unfinished_deps or []),
        }
    )
    log.info(
        "Job %s: [critical-path wait] nid=%s kind=%s wait=%.2fs reason=%s deps=%s",
        job_id,
        nid,
        kind,
        wait_sec,
        reason,
        unfinished_deps,
    )


def dag_audit_record_compile_stamp(
    job_id: str,
    *,
    kind: Optional[str],
    nid: Optional[str],
    message: str,
) -> None:
    a = dag_audit_get(job_id)
    a.setdefault("compile_progress_stamps", []).append(
        {
            "t": time.time(),
            "kind": kind,
            "nid": nid,
            "message": message[:120],
        }
    )
    if kind and kind != "executive" and "executive summary" in message.lower():
        a["misleading_executive_msgs"] = int(a.get("misleading_executive_msgs") or 0) + 1
