"""
Monotonic, concurrency-safe job result_json store.

All mutations to jobs.result_json must go through ``update_result``.
Non-result upserts must never re-serialize the result blob.
"""
from __future__ import annotations

import logging
import threading
import time
from copy import deepcopy
from typing import Any, Dict, List, Optional, Set, Tuple

log = logging.getLogger("result.state_store")

_LOCKS_GUARD = threading.Lock()
_JOB_LOCKS: Dict[str, threading.RLock] = {}
_MAX_CAS_RETRIES = 12

# Background phase monotonic order (later may replace earlier; never reverse).
_PHASE_ORDER = (
    "queued",
    "indexing",
    "embeddings",
    "carbon",
    "analytics",
    "search_ready",
    "complete",
    "done",
)

# Numeric carbon fields that must not regress toward zero once positive.
_MONOTONIC_NUMERIC = {
    "baseline_cost_gco2e",
    "estimated_baseline_pipeline_emissions_g",
    "carbon_saved_grams",
    "estimated_carbon_saved_g",
    "efficiency_percent",
    "estimated_reduction_percent",
    "local_grid_gco2_kwh",
    "total_chunks",
    "operational_co2e_g",
    "actual_cost_gco2e",
    "modeled_co2e_g",
}

_EMPTY_STRINGS = {"", "unknown", "—", "-", "none", "null"}


def _job_lock(job_id: str) -> threading.RLock:
    with _LOCKS_GUARD:
        lock = _JOB_LOCKS.get(job_id)
        if lock is None:
            lock = threading.RLock()
            _JOB_LOCKS[job_id] = lock
        return lock


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip().lower() in _EMPTY_STRINGS:
        return True
    if isinstance(value, dict) and not value:
        return True
    if isinstance(value, list) and not value:
        return True
    return False


def _is_zeroish(value: Any) -> bool:
    if value is None:
        return True
    try:
        return float(value) == 0.0
    except (TypeError, ValueError):
        return False


def _phase_rank(phase: Any) -> int:
    p = str(phase or "").lower().strip()
    try:
        return _PHASE_ORDER.index(p)
    except ValueError:
        return -1


def monotonic_deep_merge(
    base: Optional[Dict[str, Any]],
    patch: Optional[Dict[str, Any]],
    *,
    force_keys: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """
    Recursive merge: existing non-empty values win unless patch improves them.

    Never deletes keys. Never replaces non-empty dict/list with empty.
    Never overwrites non-empty / non-zero with 0 / null / {} / [] / unknown
    unless the key is in force_keys.
    """
    out: Dict[str, Any] = deepcopy(base) if isinstance(base, dict) else {}
    if not isinstance(patch, dict):
        return out
    wins = force_keys or set()

    for key, pval in patch.items():
        if key.startswith("_") and key not in ("_revision",):
            # Allow internal bookkeeping keys via force or explicit set below.
            pass
        if pval is None and key not in wins:
            continue

        if key in wins:
            out[key] = deepcopy(pval)
            continue

        cur = out.get(key)

        if isinstance(pval, dict):
            if isinstance(cur, dict):
                out[key] = monotonic_deep_merge(cur, pval, force_keys=wins)
            elif _is_empty(cur):
                out[key] = deepcopy(pval)
            # else keep existing non-empty non-dict
            continue

        if isinstance(pval, list):
            if _is_empty(pval):
                continue
            if _is_empty(cur):
                out[key] = list(pval)
            elif isinstance(cur, list):
                # Prefer longer / richer list; never shrink.
                if len(pval) >= len(cur):
                    out[key] = list(pval)
            else:
                out[key] = list(pval)
            continue

        if isinstance(pval, str):
            if _is_empty(pval):
                continue
            if _is_empty(cur):
                out[key] = pval
            elif key == "final_summary" and isinstance(cur, str):
                # Summary may only grow (or stay); never shrink.
                if len(pval) >= len(cur):
                    out[key] = pval
            elif key in ("phase",) or key.endswith("_phase"):
                if _phase_rank(pval) >= _phase_rank(cur):
                    out[key] = pval
            else:
                # Non-empty string: allow explicit upgrade from unknown → real
                if _is_empty(cur):
                    out[key] = pval
                # else keep existing
            continue

        if isinstance(pval, bool):
            # Booleans: True sticks; False cannot override True for readiness flags.
            if key in ("summary_ready", "metrics_ready", "search_ready"):
                out[key] = bool(cur) or bool(pval)
            elif cur is None:
                out[key] = pval
            elif pval is True:
                out[key] = True
            continue

        if isinstance(pval, (int, float)) and not isinstance(pval, bool):
            if key in _MONOTONIC_NUMERIC or key.endswith("_chunks") or key.endswith("_count"):
                try:
                    pv = float(pval)
                    cv = float(cur) if cur is not None and not _is_empty(cur) else 0.0
                except (TypeError, ValueError):
                    if _is_empty(cur):
                        out[key] = pval
                    continue
                # Never replace positive with zero/smaller unless patch is larger
                if pv > cv:
                    out[key] = pval
                elif _is_empty(cur) or _is_zeroish(cur):
                    if not _is_zeroish(pval):
                        out[key] = pval
                continue
            if _is_empty(cur) or _is_zeroish(cur):
                if not _is_zeroish(pval):
                    out[key] = pval
            continue

        # Fallback: fill only if empty
        if _is_empty(cur):
            out[key] = deepcopy(pval)

    return out


def apply_monotonic_guards(previous: Dict[str, Any], merged: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """
    Enforce readiness / critical-field monotonicity after merge.
    Returns (possibly repaired merged, list of blocked regressions).
    """
    blocked: List[str] = []
    out = deepcopy(merged)
    prev = previous if isinstance(previous, dict) else {}

    # summary_ready / metrics_ready / search_ready stick True
    for flag in ("summary_ready", "metrics_ready", "search_ready"):
        if prev.get(flag) is True and out.get(flag) is not True:
            out[flag] = True
            blocked.append(f"{flag}_true_sticky")

    # background.phase never moves backwards
    prev_bg = prev.get("background") if isinstance(prev.get("background"), dict) else {}
    out_bg = out.get("background") if isinstance(out.get("background"), dict) else {}
    if isinstance(prev_bg, dict) or isinstance(out_bg, dict):
        out_bg = dict(out_bg or {})
        prev_phase = prev_bg.get("phase") if isinstance(prev_bg, dict) else None
        new_phase = out_bg.get("phase")
        if _phase_rank(prev_phase) > _phase_rank(new_phase):
            out_bg["phase"] = prev_phase
            if isinstance(prev_bg, dict) and prev_bg.get("message") and _is_empty(out_bg.get("message")):
                out_bg["message"] = prev_bg.get("message")
            blocked.append(f"background_phase_backwards:{new_phase}->{prev_phase}")
        out["background"] = out_bg

    # final_summary never shrinks
    prev_sum = str(prev.get("final_summary") or "")
    new_sum = str(out.get("final_summary") or "")
    if prev_sum and len(new_sum) < len(prev_sum):
        out["final_summary"] = prev_sum
        blocked.append("summary_shrunk")

    # carbon_data critical fields
    prev_cd = prev.get("carbon_data") if isinstance(prev.get("carbon_data"), dict) else {}
    out_cd = dict(out.get("carbon_data") if isinstance(out.get("carbon_data"), dict) else {})
    if prev_cd:
        try:
            pb = float(prev_cd.get("baseline_cost_gco2e") or 0)
            nb = float(out_cd.get("baseline_cost_gco2e") or 0)
            if pb > 0 and nb < pb:
                out_cd["baseline_cost_gco2e"] = prev_cd.get("baseline_cost_gco2e")
                blocked.append("baseline_regression")
        except (TypeError, ValueError):
            pass
        # region must not become unknown after known
        prev_region = (
            (prev_cd.get("region_decision") or {}).get("selected_region_name")
            if isinstance(prev_cd.get("region_decision"), dict)
            else None
        ) or prev_cd.get("grid_zone") or prev_cd.get("compute_location")
        new_region = (
            (out_cd.get("region_decision") or {}).get("selected_region_name")
            if isinstance(out_cd.get("region_decision"), dict)
            else None
        ) or out_cd.get("grid_zone") or out_cd.get("compute_location")
        if prev_region and not _is_empty(prev_region) and _is_empty(new_region):
            if prev_cd.get("region_decision") and not out_cd.get("region_decision"):
                out_cd["region_decision"] = deepcopy(prev_cd.get("region_decision"))
            if prev_cd.get("grid_zone") and _is_empty(out_cd.get("grid_zone")):
                out_cd["grid_zone"] = prev_cd.get("grid_zone")
            if prev_cd.get("compute_location") and _is_empty(out_cd.get("compute_location")):
                out_cd["compute_location"] = prev_cd.get("compute_location")
            if prev_cd.get("local_grid_gco2_kwh") and _is_zeroish(out_cd.get("local_grid_gco2_kwh")):
                out_cd["local_grid_gco2_kwh"] = prev_cd.get("local_grid_gco2_kwh")
            blocked.append("region_regression")
        try:
            pt = float(prev_cd.get("total_chunks") or 0)
            nt = float(out_cd.get("total_chunks") or 0)
            if pt > 0 and nt < pt:
                out_cd["total_chunks"] = prev_cd.get("total_chunks")
                blocked.append("chunks_regression")
        except (TypeError, ValueError):
            pass
        out["carbon_data"] = out_cd

    # processing_insights / routing must not disappear
    if prev.get("processing_insights") and _is_empty(out.get("processing_insights")):
        out["processing_insights"] = deepcopy(prev.get("processing_insights"))
        blocked.append("processing_insights_regression")
    for rk in ("chunk_routing", "routing_distribution", "execution_plan", "hierarchy", "compile_meta"):
        prev_v = prev.get(rk)
        new_v = out.get(rk)
        if not _is_empty(prev_v) and _is_empty(new_v):
            out[rk] = deepcopy(prev_v)
            blocked.append(f"{rk}_regression")
        elif isinstance(prev_v, list) and isinstance(new_v, list) and len(new_v) < len(prev_v):
            out[rk] = deepcopy(prev_v)
            blocked.append(f"{rk}_shrunk")
        elif isinstance(prev_v, dict) and isinstance(new_v, dict):
            # ensure nested keys not wiped — already handled by merge; keep if new empty
            if prev_v and not new_v:
                out[rk] = deepcopy(prev_v)
                blocked.append(f"{rk}_regression")

    return out, blocked


def get_revision(result: Optional[Dict[str, Any]]) -> int:
    if not isinstance(result, dict):
        return 0
    try:
        return int(result.get("_revision") or 0)
    except (TypeError, ValueError):
        return 0


def update_result(
    job_id: str,
    patch: Dict[str, Any],
    source: str,
    *,
    force_keys: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """
    Single entry point for result_json mutations.

    Deep-merges ``patch`` into the current result with monotonic guards and
    compare-and-swap on ``_revision``.
    """
    if not isinstance(patch, dict):
        patch = {}
    # Never let callers clobber revision via patch
    patch = {k: v for k, v in patch.items() if k != "_revision"}

    t0 = time.perf_counter()
    retries = 0
    blocked_all: List[str] = []

    with _job_lock(job_id):
        from src.db import jobs as job_store

        while retries < _MAX_CAS_RETRIES:
            status = job_store.get_job(job_id, include_result=True) or job_store.JOB_STATUSES.get(job_id) or {}
            base = status.get("result") if isinstance(status.get("result"), dict) else {}
            base = dict(base)
            expected_rev = get_revision(base)

            merged = monotonic_deep_merge(base, patch, force_keys=force_keys)
            merged, blocked = apply_monotonic_guards(base, merged)
            blocked_all.extend(blocked)
            merged["_revision"] = expected_rev + 1

            changed = _changed_paths(base, merged)

            ok = job_store.cas_persist_result(
                job_id,
                expected_revision=expected_rev,
                new_result=merged,
            )
            if ok:
                duration_ms = (time.perf_counter() - t0) * 1000.0
                _log_contract(
                    job_id,
                    source=source,
                    rev_before=expected_rev,
                    rev_after=merged["_revision"],
                    fields_changed=changed,
                    duration_ms=duration_ms,
                    retries=retries,
                    blocked=blocked_all,
                )
                try:
                    from src.core.result_revision_log import log_result_write

                    log_result_write(
                        job_id,
                        writer=f"result_state_store:{source}",
                        previous=base,
                        new=merged,
                        extra={
                            "rev_before": expected_rev,
                            "rev_after": merged["_revision"],
                            "retries": retries,
                            "blocked": blocked_all,
                            "duration_ms": round(duration_ms, 2),
                        },
                    )
                except Exception:
                    pass
                return merged

            retries += 1

        duration_ms = (time.perf_counter() - t0) * 1000.0
        log.error(
            "RESULT_CAS_FAILED job=%s source=%s retries=%s duration_ms=%.1f",
            job_id,
            source,
            retries,
            duration_ms,
        )
        raise RuntimeError(f"result CAS failed for job {job_id} after {retries} retries (source={source})")


def _changed_paths(before: Dict[str, Any], after: Dict[str, Any], prefix: str = "") -> List[str]:
    paths: List[str] = []
    keys = set(before.keys()) | set(after.keys())
    for k in sorted(keys):
        if k == "_revision":
            continue
        p = f"{prefix}.{k}" if prefix else k
        bv, av = before.get(k), after.get(k)
        if isinstance(bv, dict) and isinstance(av, dict):
            paths.extend(_changed_paths(bv, av, p))
        elif bv != av:
            paths.append(p)
    return paths[:80]


def _log_contract(
    job_id: str,
    *,
    source: str,
    rev_before: int,
    rev_after: int,
    fields_changed: List[str],
    duration_ms: float,
    retries: int,
    blocked: List[str],
) -> None:
    log.info(
        "RESULT_UPDATE job=%s source=%s rev=%s→%s changed=%s retries=%s duration_ms=%.2f blocked=%s",
        job_id,
        source,
        rev_before,
        rev_after,
        fields_changed[:20],
        retries,
        duration_ms,
        blocked[:10],
    )
