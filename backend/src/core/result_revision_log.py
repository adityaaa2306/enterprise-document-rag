"""
Non-behavioral revision logging for job.result_json writes.

Does not change merge/replace semantics — only observes upsert_job result assignments.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

log = logging.getLogger("result.revision")

_LOCK = threading.Lock()
_REV: Dict[str, int] = {}
_LAST_FP: Dict[str, str] = {}
_LAST_KEYS: Dict[str, Set[str]] = {}
_LAST_BASELINE: Dict[str, float] = {}

_OUT_DIR = Path(__file__).resolve().parents[2] / "eval_out" / "result_revisions"
_OUT_DIR.mkdir(parents=True, exist_ok=True)


def _flat_keys(obj: Any, prefix: str = "") -> Set[str]:
    keys: Set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else str(k)
            keys.add(p)
            keys |= _flat_keys(v, p)
    elif isinstance(obj, list) and obj and isinstance(obj[0], dict):
        keys.add(f"{prefix}[]")
        keys |= _flat_keys(obj[0], f"{prefix}[]")
    return keys


def result_fingerprint(result: Optional[Dict[str, Any]]) -> str:
    if not isinstance(result, dict):
        return "empty"
    cd = result.get("carbon_data") if isinstance(result.get("carbon_data"), dict) else {}
    bg = result.get("background") if isinstance(result.get("background"), dict) else {}
    rd = cd.get("region_decision") if isinstance(cd.get("region_decision"), dict) else {}
    return "|".join(
        [
            str(bg.get("phase") or ""),
            f"{float(cd.get('baseline_cost_gco2e') or 0):.4f}",
            f"{float(cd.get('actual_cost_gco2e') or cd.get('operational_co2e_g') or 0):.4f}",
            f"{float(cd.get('carbon_saved_grams') or 0):.4f}",
            str(cd.get("grid_zone") or rd.get("selected_region_name") or cd.get("compute_location") or ""),
            str(int(float(cd.get("total_chunks") or 0))),
            "pi1" if result.get("processing_insights") else "pi0",
            "sum1" if str(result.get("final_summary") or "").strip() else "sum0",
        ]
    )


def _richness_tuple(result: Optional[Dict[str, Any]]) -> Tuple[float, float, int, int, int]:
    if not isinstance(result, dict):
        return (0.0, 0.0, 0, 0, 0)
    cd = result.get("carbon_data") if isinstance(result.get("carbon_data"), dict) else {}
    baseline = float(cd.get("baseline_cost_gco2e") or 0)
    opt = float(cd.get("actual_cost_gco2e") or cd.get("operational_co2e_g") or 0)
    has_region = 1 if (
        cd.get("region_decision")
        or cd.get("grid_zone")
        or (cd.get("compute_location") and str(cd.get("compute_location")).lower() != "unknown")
    ) else 0
    has_routing = 1 if (result.get("chunk_routing") or result.get("routing_distribution")) else 0
    has_pi = 1 if result.get("processing_insights") else 0
    return (baseline, opt, has_region, has_routing, has_pi)


def is_monotonic_regression(prev: Optional[Dict[str, Any]], new: Optional[Dict[str, Any]]) -> List[str]:
    """Return list of monotonicity violations when new loses richness vs prev."""
    violations: List[str] = []
    if not isinstance(prev, dict) or not isinstance(new, dict):
        return violations
    pb, po, pr, prout, ppi = _richness_tuple(prev)
    nb, no, nr, nrout, npi = _richness_tuple(new)
    if pb > 0 and nb < pb * 0.5 and nb <= 0.0001:
        violations.append(f"baseline_reset:{pb}->{nb}")
    if po > 0 and no <= 0 and pb >= 0:
        violations.append(f"optimized_lost:{po}->{no}")
    if pr and not nr:
        violations.append("region_disappeared")
    if prout and not nrout:
        violations.append("routing_disappeared")
    if ppi and not npi:
        violations.append("processing_insights_disappeared")
    prev_bg = (prev.get("background") or {}).get("phase") if isinstance(prev.get("background"), dict) else ""
    new_bg = (new.get("background") or {}).get("phase") if isinstance(new.get("background"), dict) else ""
    order = ["queued", "indexing", "embeddings", "carbon", "analytics", "search_ready", "complete", "done"]
    try:
        if prev_bg in order and new_bg in order and order.index(new_bg) < order.index(prev_bg):
            # analytics after search_ready in result blob is a regression of phase stamp
            if not (prev_bg == "search_ready" and new_bg in ("carbon", "analytics")):
                violations.append(f"background_phase_backwards:{prev_bg}->{new_bg}")
    except ValueError:
        pass
    return violations


def log_result_write(
    job_id: str,
    *,
    writer: str,
    previous: Optional[Dict[str, Any]],
    new: Optional[Dict[str, Any]],
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Observe a result_json assignment. Safe to call from upsert_job."""
    prev = previous if isinstance(previous, dict) else None
    nxt = new if isinstance(new, dict) else None
    prev_keys = _LAST_KEYS.get(job_id) or (_flat_keys(prev) if prev else set())
    new_keys = _flat_keys(nxt) if nxt else set()
    added = sorted(new_keys - prev_keys)
    removed = sorted(prev_keys - new_keys)
    prev_fp = _LAST_FP.get(job_id) or result_fingerprint(prev)
    new_fp = result_fingerprint(nxt)
    violations = is_monotonic_regression(prev, nxt)

    with _LOCK:
        rev = _REV.get(job_id, 0) + 1
        _REV[job_id] = rev
        _LAST_FP[job_id] = new_fp
        _LAST_KEYS[job_id] = new_keys
        try:
            _LAST_BASELINE[job_id] = float(
                ((nxt or {}).get("carbon_data") or {}).get("baseline_cost_gco2e") or 0
            )
        except Exception:
            _LAST_BASELINE[job_id] = 0.0

    event = {
        "t": time.time(),
        "t_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "job_id": job_id,
        "revision": rev,
        "writer": writer,
        "sync_key_prev": prev_fp,
        "sync_key": new_fp,
        "sync_key_changed": prev_fp != new_fp,
        "keys_added_count": len(added),
        "keys_removed_count": len(removed),
        "keys_added_sample": added[:40],
        "keys_removed_sample": removed[:40],
        "monotonicity_violations": violations,
        "baseline": _richness_tuple(nxt)[0],
        "optimized": _richness_tuple(nxt)[1],
        "has_region": bool(_richness_tuple(nxt)[2]),
        "has_routing": bool(_richness_tuple(nxt)[3]),
        "background_phase": ((nxt or {}).get("background") or {}).get("phase")
        if isinstance((nxt or {}).get("background"), dict)
        else None,
        "extra": extra or {},
    }

    line = json.dumps(event, default=str)
    log.info("RESULT_REVISION %s", line)
    try:
        path = _OUT_DIR / f"{job_id}.jsonl"
        with _LOCK:
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        # Global stream for multi-job runs
        with _LOCK:
            with (_OUT_DIR / "_all.jsonl").open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception as e:
        log.debug("revision file write failed: %s", e)
    return event


def log_result_read(
    job_id: str,
    *,
    endpoint: str,
    result: Optional[Dict[str, Any]],
    status_fields: Optional[Dict[str, Any]] = None,
) -> None:
    event = {
        "t": time.time(),
        "t_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "job_id": job_id,
        "kind": "READ",
        "endpoint": endpoint,
        "revision_known": _REV.get(job_id),
        "sync_key": result_fingerprint(result if isinstance(result, dict) else None),
        "baseline": _richness_tuple(result if isinstance(result, dict) else None)[0],
        "optimized": _richness_tuple(result if isinstance(result, dict) else None)[1],
        "has_region": bool(_richness_tuple(result if isinstance(result, dict) else None)[2]),
        "status": (status_fields or {}),
    }
    line = json.dumps(event, default=str)
    log.info("RESULT_READ %s", line)
    try:
        with _LOCK:
            with (_OUT_DIR / f"{job_id}.reads.jsonl").open("a", encoding="utf-8") as f:
                f.write(line + "\n")
            with (_OUT_DIR / "_all_reads.jsonl").open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass
