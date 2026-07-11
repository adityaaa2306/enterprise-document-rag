"""
Job status persistence + durable queue (Phase 3).

When PERSIST_JOBS_TO_DB is True, job state is durable in the ``jobs`` table.
An in-process cache is still maintained for hot progress updates within a worker.
Queue claim uses row locking (Postgres FOR UPDATE SKIP LOCKED; SQLite exclusive txn).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, or_, select, update

from src.core import job_status as job_status_mod
from src.core.config import settings

log = logging.getLogger("db.jobs")

# Process-local cache (also exported as JOB_STATUSES for backward compatibility)
JOB_STATUSES: Dict[str, Dict[str, Any]] = {}


def _db_enabled() -> bool:
    return bool(getattr(settings, "PERSIST_JOBS_TO_DB", True))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _extract_metrics(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Pull indexed metric fields from a status/result/routing payload."""
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    insights = result.get("processing_insights") if isinstance(result.get("processing_insights"), dict) else {}
    carbon = result.get("carbon_data") if isinstance(result.get("carbon_data"), dict) else {}
    routing = payload.get("routing_decision")

    selected_model = payload.get("selected_model") or insights.get("selected_model")
    if selected_model is None and isinstance(routing, dict):
        selected_model = routing.get("selected_model")
    crs = payload.get("crs")
    if crs is None:
        crs = insights.get("crs")
    confidence = payload.get("confidence")
    if confidence is None:
        confidence = insights.get("confidence")
    latency_ms = payload.get("latency_ms")
    if latency_ms is None:
        latency_ms = insights.get("latency_ms")
    carbon_saved = payload.get("carbon_saved_grams")
    if carbon_saved is None:
        carbon_saved = carbon.get("carbon_saved_grams")

    return {
        "selected_model": selected_model,
        "crs": float(crs) if crs is not None else None,
        "confidence": float(confidence) if confidence is not None else None,
        "latency_ms": float(latency_ms) if latency_ms is not None else None,
        "carbon_saved_grams": float(carbon_saved) if carbon_saved is not None else None,
        "routing_decision": routing if isinstance(routing, dict) else payload.get("routing_decision"),
    }


def upsert_job(job_id: str, **fields: Any) -> Dict[str, Any]:
    """
    Merge fields into the in-memory cache and optionally persist to DB.

    Returns the full status dict (same shape as legacy JOB_STATUSES[job_id]).
    """
    current = dict(JOB_STATUSES.get(job_id) or {})
    prev_status = current.get("status")
    for k, v in fields.items():
        current[k] = v
    current["job_id"] = job_id
    JOB_STATUSES[job_id] = current

    new_status = current.get("status")
    if "status" in fields and new_status is not None and str(new_status) != str(prev_status or ""):
        msg = current.get("message") or ""
        log.info(
            "Job %s: status %s → %s%s",
            job_id,
            prev_status or "(none)",
            new_status,
            f" | {msg}" if msg else "",
        )

    if _db_enabled():
        try:
            _persist(job_id, current, fields)
        except Exception as e:
            log.error(f"Failed to persist job {job_id}: {e}")

    return current


def enqueue_job(
    job_id: str,
    *,
    user_id: Optional[int] = None,
    filename: Optional[str] = None,
    job_mode: Optional[str] = None,
    message: str = "Queued. Waiting for worker...",
) -> Dict[str, Any]:
    """Create a durable pending job (API path — no AI work)."""
    now = _now()
    return upsert_job(
        job_id,
        status=job_status_mod.STATUS_PENDING,
        progress=0.0,
        message=message,
        understanding="pending" if settings.ENABLE_UNDERSTANDING else "skipped",
        filename=filename,
        job_mode=job_mode,
        user_id=user_id,
        attempt_count=0,
        available_at=now,
        claimed_at=None,
        claimed_by=None,
        heartbeat_at=None,
        error_detail=None,
    )


def set_progress(job_id: str, progress: float, message: str) -> None:
    status = JOB_STATUSES.get(job_id, {}).get("status") or job_status_mod.STATUS_PROCESSING
    upsert_job(job_id, progress=progress, message=message, status=status)


def set_understanding(job_id: str, value: str) -> None:
    upsert_job(job_id, understanding=value)


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """
    Read job status.

    When durable DB mode is on, always refresh from Postgres/SQLite so the API
    process sees worker claim/progress updates (in-memory cache is per-process).
    """
    if _db_enabled():
        try:
            from src.db.models import JobModel
            from src.db.session import get_session

            db = get_session()
            try:
                row = db.get(JobModel, job_id)
                if not row:
                    return JOB_STATUSES.get(job_id)
                status = _row_to_status(row)
                JOB_STATUSES[job_id] = status
                return status
            finally:
                db.close()
        except Exception as e:
            log.error(f"Failed to load job {job_id} from DB: {e}")
            return JOB_STATUSES.get(job_id)

    return JOB_STATUSES.get(job_id)


def touch_job_heartbeat(job_id: str, worker_id: str) -> None:
    """Refresh job + worker heartbeats while processing."""
    now = _now()
    upsert_job(job_id, heartbeat_at=now, claimed_by=worker_id, status=job_status_mod.STATUS_PROCESSING)
    try:
        upsert_worker_heartbeat(worker_id, status="busy", meta={"current_job_id": job_id})
    except Exception as e:
        log.warning(f"Worker heartbeat update failed: {e}")


def claim_next_job(worker_id: str) -> Optional[Dict[str, Any]]:
    """
    Atomically claim the next available pending job.

    Postgres: SELECT … FOR UPDATE SKIP LOCKED
    SQLite: single UPDATE…WHERE id=(SELECT…) under an exclusive transaction
    """
    if not _db_enabled():
        log.error("claim_next_job requires PERSIST_JOBS_TO_DB=true")
        return None

    from sqlalchemy import text

    from src.db.models import JobModel
    from src.db.session import get_engine, get_session, is_postgres

    now = _now()
    db = get_session()
    try:
        if is_postgres():
            stmt = (
                select(JobModel)
                .where(
                    JobModel.status == job_status_mod.STATUS_PENDING,
                    or_(JobModel.available_at.is_(None), JobModel.available_at <= now),
                )
                .order_by(JobModel.created_at.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            row = db.execute(stmt).scalars().first()
            if row is None:
                db.rollback()
                return None
            row.status = job_status_mod.STATUS_PROCESSING
            row.claimed_at = now
            row.claimed_by = worker_id
            row.heartbeat_at = now
            row.attempt_count = int(row.attempt_count or 0) + 1
            row.message = "Claimed by worker. Preparing agentic graph..."
            row.progress = max(float(row.progress or 0.0), 1.0)
            row.updated_at = now
            db.commit()
            status = _row_to_status(row)
            JOB_STATUSES[row.id] = status
            return status

        # SQLite / fallback: exclusive lock + conditional update
        engine = get_engine()
        pick = None
        with engine.connect() as conn:
            if engine.dialect.name == "sqlite":
                conn.execute(text("BEGIN IMMEDIATE"))
            else:
                conn.begin()
            try:
                pick = conn.execute(
                    select(JobModel.id)
                    .where(
                        JobModel.status == job_status_mod.STATUS_PENDING,
                        or_(JobModel.available_at.is_(None), JobModel.available_at <= now),
                    )
                    .order_by(JobModel.created_at.asc())
                    .limit(1)
                ).scalar_one_or_none()
                if pick is None:
                    conn.rollback()
                    return None
                result = conn.execute(
                    update(JobModel)
                    .where(
                        JobModel.id == pick,
                        JobModel.status == job_status_mod.STATUS_PENDING,
                    )
                    .values(
                        status=job_status_mod.STATUS_PROCESSING,
                        claimed_at=now,
                        claimed_by=worker_id,
                        heartbeat_at=now,
                        attempt_count=JobModel.attempt_count + 1,
                        message="Claimed by worker. Preparing agentic graph...",
                        progress=1.0,
                        updated_at=now,
                    )
                )
                if result.rowcount != 1:
                    conn.rollback()
                    return None
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        row = db.get(JobModel, pick)
        if not row:
            return None
        db.expire(row)
        row = db.get(JobModel, pick)
        status = _row_to_status(row)
        JOB_STATUSES[row.id] = status
        return status
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        log.error(f"claim_next_job failed: {e}")
        return None
    finally:
        db.close()


def reclaim_stale_jobs(
    *,
    stale_after_sec: Optional[int] = None,
    max_attempts: Optional[int] = None,
) -> int:
    """
    Requeue processing jobs whose heartbeat/claim is older than the timeout.
    Jobs that exceeded max attempts are marked error.
    Returns number of rows touched.
    """
    if not _db_enabled():
        return 0

    from src.db.models import JobModel
    from src.db.session import get_session

    ttl = int(stale_after_sec if stale_after_sec is not None else settings.WORKER_CLAIM_TIMEOUT_SEC)
    max_att = int(max_attempts if max_attempts is not None else settings.WORKER_MAX_ATTEMPTS)
    cutoff = _now() - timedelta(seconds=ttl)
    now = _now()
    backoff = int(getattr(settings, "WORKER_RETRY_BACKOFF_SEC", 30) or 30)

    db = get_session()
    touched = 0
    try:
        rows: List[JobModel] = (
            db.execute(
                select(JobModel).where(
                    JobModel.status == job_status_mod.STATUS_PROCESSING,
                    or_(
                        and_(JobModel.heartbeat_at.is_not(None), JobModel.heartbeat_at < cutoff),
                        and_(JobModel.heartbeat_at.is_(None), JobModel.claimed_at.is_not(None), JobModel.claimed_at < cutoff),
                        and_(JobModel.heartbeat_at.is_(None), JobModel.claimed_at.is_(None), JobModel.updated_at < cutoff),
                    ),
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            attempts = int(row.attempt_count or 0)
            if attempts >= max_att:
                row.status = job_status_mod.STATUS_ERROR
                row.message = "Job failed: exceeded max attempts after worker timeout"
                row.error_detail = row.error_detail or "stale_claim_max_attempts"
                row.completed_at = now
                row.claimed_by = None
                row.claimed_at = None
                row.heartbeat_at = None
            else:
                row.status = job_status_mod.STATUS_PENDING
                row.message = "Requeued after stale worker claim"
                row.claimed_by = None
                row.claimed_at = None
                row.heartbeat_at = None
                row.available_at = now + timedelta(seconds=backoff * max(attempts, 1))
                row.progress = 0.0
            row.updated_at = now
            JOB_STATUSES.pop(row.id, None)
            touched += 1
        db.commit()
        if touched:
            log.warning(f"Reclaimed/failed {touched} stale processing job(s)")
        return touched
    except Exception as e:
        db.rollback()
        log.error(f"reclaim_stale_jobs failed: {e}")
        return 0
    finally:
        db.close()


def fail_or_retry_job(
    job_id: str,
    *,
    error: str,
    worker_id: Optional[str] = None,
) -> Dict[str, Any]:
    """On worker exception: retry (pending) or terminal error."""
    current = get_job(job_id) or {}
    attempts = int(current.get("attempt_count") or 0)
    max_att = int(settings.WORKER_MAX_ATTEMPTS)
    backoff = int(getattr(settings, "WORKER_RETRY_BACKOFF_SEC", 30) or 30)
    now = _now()

    # Never leave a job stuck in processing after a failure path.
    if attempts < max_att:
        log.warning(
            "Job %s: processing → pending (retry %s/%s) | %s",
            job_id,
            attempts,
            max_att,
            error,
        )
        return upsert_job(
            job_id,
            status=job_status_mod.STATUS_PENDING,
            progress=0.0,
            message=f"Retry scheduled after failure (attempt {attempts}/{max_att}): {error}",
            error_detail=error,
            claimed_at=None,
            claimed_by=None,
            heartbeat_at=None,
            available_at=now + timedelta(seconds=backoff * max(attempts, 1)),
            understanding="skipped",
        )

    log.error("Job %s: processing → error (terminal) | %s", job_id, error)
    return upsert_job(
        job_id,
        status=job_status_mod.STATUS_ERROR,
        progress=100.0,
        message=error,
        error_detail=error,
        claimed_at=None,
        claimed_by=None,
        heartbeat_at=None,
        understanding="skipped",
        user_id=current.get("user_id"),
    )


def upsert_worker_heartbeat(
    worker_id: str,
    *,
    status: str = "idle",
    hostname: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    if not _db_enabled():
        return
    from src.db.models import WorkerHeartbeatModel
    from src.db.session import get_session
    import socket

    db = get_session()
    try:
        row = db.get(WorkerHeartbeatModel, worker_id)
        now = _now()
        if row is None:
            row = WorkerHeartbeatModel(
                worker_id=worker_id,
                hostname=hostname or socket.gethostname(),
                status=status,
                last_seen_at=now,
                meta_json=meta,
            )
            db.add(row)
        else:
            row.status = status
            row.last_seen_at = now
            if hostname:
                row.hostname = hostname
            if meta is not None:
                row.meta_json = meta
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def list_worker_heartbeats(*, stale_after_sec: Optional[int] = None) -> List[Dict[str, Any]]:
    if not _db_enabled():
        return []
    from src.db.models import WorkerHeartbeatModel
    from src.db.session import get_session

    ttl = int(stale_after_sec if stale_after_sec is not None else settings.WORKER_HEARTBEAT_STALE_SEC)
    cutoff = _now() - timedelta(seconds=ttl)
    db = get_session()
    try:
        rows = db.execute(select(WorkerHeartbeatModel).order_by(WorkerHeartbeatModel.last_seen_at.desc())).scalars().all()
        out = []
        for r in rows:
            last = r.last_seen_at
            if last is not None and last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            alive = last is not None and last >= cutoff
            out.append(
                {
                    "worker_id": r.worker_id,
                    "hostname": r.hostname,
                    "status": r.status,
                    "last_seen_at": last.isoformat() if last else None,
                    "alive": alive,
                    "meta": r.meta_json,
                }
            )
        return out
    finally:
        db.close()


def _row_to_status(row) -> Dict[str, Any]:
    status: Dict[str, Any] = {
        "job_id": row.id,
        "status": row.status,
        "progress": row.progress if row.progress is not None else 0.0,
        "message": row.message or "",
        "understanding": row.understanding,
        "attempt_count": int(getattr(row, "attempt_count", 0) or 0),
        "claimed_by": getattr(row, "claimed_by", None),
    }
    if row.user_id is not None:
        status["user_id"] = row.user_id
    if row.result_json is not None:
        status["result"] = row.result_json
    if row.error_detail:
        status["error_detail"] = row.error_detail
    if row.filename:
        status["filename"] = row.filename
    if row.job_mode:
        status["job_mode"] = row.job_mode
    if row.selected_model:
        status["selected_model"] = row.selected_model
    if row.crs is not None:
        status["crs"] = row.crs
    if row.confidence is not None:
        status["confidence"] = row.confidence
    if row.latency_ms is not None:
        status["latency_ms"] = row.latency_ms
    if row.routing_decision is not None:
        status["routing_decision"] = row.routing_decision
    if getattr(row, "available_at", None) is not None:
        status["available_at"] = row.available_at
    if getattr(row, "heartbeat_at", None) is not None:
        status["heartbeat_at"] = row.heartbeat_at
    return status


def _persist(job_id: str, current: Dict[str, Any], fields: Dict[str, Any]) -> None:
    from src.db.models import JobModel
    from src.db.session import get_session

    metrics = _extract_metrics(current)
    db = get_session()
    try:
        row = db.get(JobModel, job_id)
        if row is None:
            row = JobModel(id=job_id, status=str(current.get("status") or job_status_mod.STATUS_PENDING))
            db.add(row)

        if "status" in current:
            row.status = str(current["status"])
        if "progress" in current and current["progress"] is not None:
            row.progress = float(current["progress"])
        if "message" in current:
            row.message = current.get("message")
        if "understanding" in current:
            row.understanding = current.get("understanding")
        if "result" in current:
            row.result_json = current.get("result")
        if "error_detail" in current:
            row.error_detail = current.get("error_detail")
        if "filename" in current:
            row.filename = current.get("filename")
        if "job_mode" in current:
            row.job_mode = current.get("job_mode")

        for key in ("selected_model", "crs", "confidence", "latency_ms", "carbon_saved_grams", "routing_decision"):
            val = metrics.get(key)
            if val is not None:
                setattr(row, key, val)
            elif key in fields and fields[key] is not None:
                setattr(row, key, fields[key])

        if "user_id" in current and current["user_id"] is not None:
            row.user_id = int(current["user_id"])
        elif "user_id" in fields and fields["user_id"] is not None:
            row.user_id = int(fields["user_id"])

        for col in ("claimed_at", "claimed_by", "available_at", "heartbeat_at"):
            if col in fields:
                setattr(row, col, fields[col])
            elif col in current:
                setattr(row, col, current[col])

        if "attempt_count" in fields and fields["attempt_count"] is not None:
            row.attempt_count = int(fields["attempt_count"])
        elif "attempt_count" in current and current["attempt_count"] is not None:
            row.attempt_count = int(current["attempt_count"])

        if str(current.get("status")) in (
            job_status_mod.STATUS_COMPLETE,
            job_status_mod.STATUS_ERROR,
            job_status_mod.STATUS_CANCELLED,
        ):
            if row.completed_at is None:
                row.completed_at = _now()
            row.claimed_by = None
            row.heartbeat_at = None

        row.updated_at = _now()
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
