"""
Routing telemetry — immutable decision logs for recalibration.

Dual-write: Postgres ``routing_events`` (when enabled) + optional JSONL fallback.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.core.config import settings

log = logging.getLogger(__name__)
_lock = threading.Lock()


def _log_path() -> str:
    path = settings.ROUTING_TELEMETRY_PATH
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    return path


def _write_jsonl(event: Dict[str, Any]) -> None:
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        **event,
    }
    with _lock:
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, default=str) + "\n")


def _recent_jsonl(limit: int = 50) -> List[Dict[str, Any]]:
    path = _log_path()
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    out: List[Dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def record_routing_event(event: Dict[str, Any]) -> None:
    """Append one telemetry event (DB and/or JSONL per feature flags)."""
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        **event,
    }
    db_ok = False
    try:
        from src.db import routing_events as re_db

        if re_db.db_enabled():
            re_db.insert_event(payload)
            db_ok = True
    except Exception as e:
        log.error(f"Failed to write routing telemetry to DB: {e}")

    write_jsonl = bool(getattr(settings, "ROUTING_TELEMETRY_JSONL_FALLBACK", True)) or not db_ok
    if write_jsonl:
        try:
            _write_jsonl(event)
        except Exception as e:
            log.error(f"Failed to write routing telemetry JSONL: {e}")

    log.info(
        f"Telemetry: job={event.get('job_id')} crs={event.get('crs')} "
        f"model={event.get('selected_model')} escalations={event.get('escalation_count')}"
    )


def log_job_routing(
    job_id: str,
    mode: str,
    features: Dict[str, Any],
    cre: Dict[str, Any],
    decision: Dict[str, Any],
    validation: Optional[Dict[str, Any]],
    carbon_report: Optional[Dict[str, Any]] = None,
    latency_ms: Optional[float] = None,
) -> None:
    record_routing_event({
        "event": "routing_decision",
        "job_id": job_id,
        "mode": mode,
        "crs": cre.get("crs"),
        "crs_raw": cre.get("crs_raw"),
        "domain_floor": cre.get("domain_floor"),
        "min_tier": cre.get("min_tier"),
        "selected_model": decision.get("selected_model"),
        "tier": decision.get("tier"),
        "compile_tier": decision.get("compile_tier"),
        "routing_rationale": decision.get("reason_summary"),
        "utility_ranking": decision.get("utility_ranking"),
        "validation_confidence": (validation or {}).get("confidence"),
        "validation_passed": (validation or {}).get("passed"),
        "escalation_count": len(decision.get("escalations") or []),
        "carbon_estimate": (carbon_report or {}).get("actual_cost_gco2e"),
        "latency_ms": latency_ms,
        "api_health": (features.get("runtime") or {}).get("api_health"),
        "document_type": features.get("document_type"),
        "domain_label": features.get("domain_label"),
        "policy_version": cre.get("policy_version"),
        "features_snapshot": {
            "reasoning": features.get("reasoning_score"),
            "structural": features.get("structural_score"),
            "coherence": features.get("coherence_score"),
            "retrieval_confidence": features.get("retrieval_confidence"),
            "ocr_confidence": features.get("ocr_confidence"),
        },
    })


def recent_events(limit: int = 50) -> List[Dict[str, Any]]:
    try:
        from src.db import routing_events as re_db

        if re_db.db_enabled():
            return re_db.recent_from_db(limit)
    except Exception as e:
        log.warning(f"DB recent_events failed, using JSONL: {e}")
    return _recent_jsonl(limit)
