"""Routing event DB repository (no JSONL — callers handle dual-write)."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from src.core.config import settings

log = logging.getLogger("db.routing_events")


def db_enabled() -> bool:
    return bool(getattr(settings, "PERSIST_ROUTING_EVENTS_TO_DB", True))


def insert_event(event: Dict[str, Any], *, user_id: Optional[int] = None) -> None:
    from src.db.models import RoutingEventModel
    from src.db.session import get_session

    db = get_session()
    try:
        row = RoutingEventModel(
            job_id=event.get("job_id"),
            user_id=user_id,
            event_type=event.get("event") or event.get("event_type"),
            selected_model=event.get("selected_model"),
            crs=_as_float(event.get("crs")),
            confidence=_as_float(
                event.get("confidence")
                if event.get("confidence") is not None
                else event.get("validation_confidence")
            ),
            latency_ms=_as_float(event.get("latency_ms")),
            carbon=_as_float(
                event.get("carbon")
                if event.get("carbon") is not None
                else event.get("carbon_estimate")
            ),
            event=dict(event),
        )
        db.add(row)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _as_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def recent_from_db(limit: int = 50) -> List[Dict[str, Any]]:
    from src.db.models import RoutingEventModel
    from src.db.session import get_session

    db = get_session()
    try:
        rows = (
            db.query(RoutingEventModel)
            .order_by(RoutingEventModel.id.desc())
            .limit(limit)
            .all()
        )
        out: List[Dict[str, Any]] = []
        for r in reversed(rows):
            payload = dict(r.event or {})
            if r.created_at and "ts" not in payload:
                payload["ts"] = r.created_at.isoformat()
            out.append(payload)
        return out
    finally:
        db.close()
