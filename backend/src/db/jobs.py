"""
Job status persistence + durable queue (Phase 3).

When PERSIST_JOBS_TO_DB is True, job state is durable in the ``jobs`` table.
An in-process cache is still maintained for hot progress updates within a worker.
Queue claim uses row locking (Postgres FOR UPDATE SKIP LOCKED; SQLite exclusive txn).
"""
from __future__ import annotations

import logging
import threading
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
    current = JOB_STATUSES.get(job_id) or {}
    status = current.get("status") or job_status_mod.STATUS_PROCESSING
    # Never reopen a finished job via a late progress tick.
    if str(status) in (
        job_status_mod.STATUS_COMPLETE,
        job_status_mod.STATUS_ERROR,
        job_status_mod.STATUS_CANCELLED,
    ):
        return
    upsert_job(job_id, progress=progress, message=message, status=status)


def set_understanding(job_id: str, value: str) -> None:
    upsert_job(job_id, understanding=value)


def get_job(job_id: str, *, include_result: bool = True) -> Optional[Dict[str, Any]]:
    """
    Read job status.

    When durable DB mode is on, refresh from Postgres/SQLite so a separate API
    process sees worker updates. In the embedded-worker process, never clobber a
    fresher in-memory progress/message with a stale DB row (throttle window).

    Pass ``include_result=False`` for polling endpoints (``/job-status``) so the
    large ``result_json`` blob is not deserialized on every tick. Response shape
    for callers that ignore ``result`` is unchanged.
    """
    mem = JOB_STATUSES.get(job_id)
    if _db_enabled():
        try:
            from sqlalchemy.orm import load_only

            from src.db.models import JobModel
            from src.db.session import get_session

            db = get_session()
            try:
                if include_result:
                    row = db.get(JobModel, job_id)
                else:
                    row = (
                        db.execute(
                            select(JobModel)
                            .where(JobModel.id == job_id)
                            .options(
                                load_only(
                                    JobModel.id,
                                    JobModel.user_id,
                                    JobModel.status,
                                    JobModel.progress,
                                    JobModel.message,
                                    JobModel.filename,
                                    JobModel.job_mode,
                                    JobModel.claimed_by,
                                    JobModel.attempt_count,
                                    JobModel.error_detail,
                                    JobModel.available_at,
                                    JobModel.heartbeat_at,
                                    JobModel.created_at,
                                    JobModel.updated_at,
                                    JobModel.completed_at,
                                )
                            )
                        )
                        .scalars()
                        .first()
                    )
                if not row:
                    if not include_result and mem:
                        light = dict(mem)
                        light.pop("result", None)
                        light.pop("understanding", None)
                        light.pop("routing_decision", None)
                        return light
                    return mem
                status = _row_to_status(row, include_result=include_result)
                if mem and str(mem.get("status") or "") in (
                    job_status_mod.STATUS_PROCESSING,
                    job_status_mod.STATUS_PENDING,
                ):
                    try:
                        mem_prog = float(mem.get("progress") or 0.0)
                        db_prog = float(status.get("progress") or 0.0)
                    except (TypeError, ValueError):
                        mem_prog, db_prog = 0.0, 0.0
                    # Prefer live worker cache when it is ahead of durable row
                    if mem_prog >= db_prog and mem.get("message"):
                        status["progress"] = mem_prog
                        status["message"] = mem.get("message") or status.get("message")
                        if mem.get("partial") is not None:
                            status["partial"] = mem.get("partial")
                        if mem.get("status"):
                            status["status"] = mem.get("status")
                # Keep in-memory result when this read intentionally skipped it.
                if not include_result and mem and mem.get("result") is not None:
                    cached = dict(mem)
                    cached.update(status)
                    cached["result"] = mem["result"]
                    JOB_STATUSES[job_id] = cached
                else:
                    JOB_STATUSES[job_id] = status
                return status
            finally:
                db.close()
        except Exception as e:
            log.error(f"Failed to load job {job_id} from DB: {e}")
            if not include_result and mem:
                light = dict(mem)
                light.pop("result", None)
                light.pop("understanding", None)
                light.pop("routing_decision", None)
                return light
            return mem

    if not include_result and mem:
        light = dict(mem)
        light.pop("result", None)
        light.pop("understanding", None)
        light.pop("routing_decision", None)
        return light
    return mem


def touch_job_heartbeat(job_id: str, worker_id: str) -> None:
    """Refresh job + worker heartbeats while processing.

    Never downgrade a terminal job back to ``processing`` (that race left jobs
    stuck at "Finalizing results..." forever while ``result_json`` was already saved).
    """
    now = _now()
    current = JOB_STATUSES.get(job_id) or {}
    status = str(current.get("status") or "")
    if status in (
        job_status_mod.STATUS_COMPLETE,
        job_status_mod.STATUS_ERROR,
        job_status_mod.STATUS_CANCELLED,
    ):
        return
    # Heartbeat-only write: do not force status=processing if absent from cache;
    # _persist path below still guards terminal rows in DB.
    upsert_job(job_id, heartbeat_at=now, claimed_by=worker_id)
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


def release_orphaned_claims_for_worker(worker_id: str) -> int:
    """
    On worker process start, any ``processing`` job still claimed by this
    worker_id cannot still be running (this process just booted). Requeue them
    immediately so restarts do not leave the UI stuck for WORKER_CLAIM_TIMEOUT_SEC.
    """
    if not _db_enabled() or not (worker_id or "").strip():
        return 0

    from src.db.models import JobModel
    from src.db.session import get_session

    wid = str(worker_id).strip()
    now = _now()
    backoff = int(getattr(settings, "WORKER_RETRY_BACKOFF_SEC", 30) or 30)
    db = get_session()
    touched = 0
    try:
        rows: List[JobModel] = (
            db.execute(
                select(JobModel).where(
                    JobModel.status == job_status_mod.STATUS_PROCESSING,
                    JobModel.claimed_by == wid,
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            attempts = int(row.attempt_count or 0)
            row.status = job_status_mod.STATUS_PENDING
            row.message = (
                "Requeued after worker restart (orphaned claim). "
                "Previous attempt was interrupted mid-pipeline."
            )
            row.error_detail = "orphaned_claim_on_worker_start"
            row.claimed_by = None
            row.claimed_at = None
            row.heartbeat_at = None
            row.available_at = now + timedelta(seconds=backoff * max(attempts, 1))
            # Keep progress for UI history; claim path resets when processing resumes.
            row.updated_at = now
            JOB_STATUSES.pop(row.id, None)
            touched += 1
            log.warning(
                "Released orphaned claim job=%s worker=%s attempt=%s",
                row.id,
                wid,
                attempts,
            )
        if touched:
            db.commit()
        return touched
    except Exception as e:
        db.rollback()
        log.error(f"release_orphaned_claims_for_worker failed: {e}")
        return 0
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
    if str(current.get("status") or "") == job_status_mod.STATUS_CANCELLED:
        clear_cancel_request(job_id)
        return current
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


def _row_to_status(row, *, include_result: bool = True) -> Dict[str, Any]:
    status: Dict[str, Any] = {
        "job_id": row.id,
        "status": row.status,
        "progress": row.progress if row.progress is not None else 0.0,
        "message": row.message or "",
        "understanding": getattr(row, "understanding", None) if include_result else None,
        "attempt_count": int(getattr(row, "attempt_count", 0) or 0),
        "claimed_by": getattr(row, "claimed_by", None),
    }
    if row.user_id is not None:
        status["user_id"] = row.user_id
    if include_result and row.result_json is not None:
        status["result"] = row.result_json
    if include_result and row.error_detail:
        status["error_detail"] = row.error_detail
    elif (not include_result) and getattr(row, "error_detail", None):
        # Keep a short error signal for list UIs without loading huge payloads.
        status["error_detail"] = row.error_detail
    if row.filename:
        status["filename"] = row.filename
    if row.job_mode:
        status["job_mode"] = row.job_mode
    if include_result and row.selected_model:
        status["selected_model"] = row.selected_model
    if include_result and row.crs is not None:
        status["crs"] = row.crs
    if include_result and row.confidence is not None:
        status["confidence"] = row.confidence
    if include_result and row.latency_ms is not None:
        status["latency_ms"] = row.latency_ms
    if include_result and row.routing_decision is not None:
        status["routing_decision"] = row.routing_decision
    if getattr(row, "available_at", None) is not None:
        status["available_at"] = row.available_at
    if getattr(row, "heartbeat_at", None) is not None:
        status["heartbeat_at"] = row.heartbeat_at
    if getattr(row, "created_at", None) is not None:
        status["created_at"] = row.created_at
    if getattr(row, "updated_at", None) is not None:
        status["updated_at"] = row.updated_at
    if getattr(row, "completed_at", None) is not None:
        status["completed_at"] = row.completed_at
    return status


_CANCEL_LOCK = threading.Lock()
_CANCEL_REQUESTS: set = set()


def request_cancel(job_id: str) -> None:
    with _CANCEL_LOCK:
        _CANCEL_REQUESTS.add(str(job_id))


def clear_cancel_request(job_id: str) -> None:
    with _CANCEL_LOCK:
        _CANCEL_REQUESTS.discard(str(job_id))


def is_cancel_requested(job_id: str) -> bool:
    with _CANCEL_LOCK:
        if str(job_id) in _CANCEL_REQUESTS:
            return True
    cur = JOB_STATUSES.get(job_id) or {}
    if str(cur.get("status") or "") == job_status_mod.STATUS_CANCELLED:
        return True
    # Durable check (cross-process cancel from API → worker)
    if _db_enabled():
        try:
            from src.db.models import JobModel
            from src.db.session import get_session

            db = get_session()
            try:
                row = db.get(JobModel, job_id)
                return bool(
                    row is not None
                    and str(row.status) == job_status_mod.STATUS_CANCELLED
                )
            finally:
                db.close()
        except Exception:
            return False
    return False


def cancel_job(job_id: str, *, user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """
    Mark a pending/processing job cancelled so the worker can free the slot.

    Already-terminal jobs are returned unchanged (idempotent).
    """
    current = get_job(job_id)
    if not current:
        return None
    if user_id is not None and current.get("user_id") is not None:
        if int(current["user_id"]) != int(user_id):
            raise PermissionError("Not the job owner")

    status = str(current.get("status") or "")
    if status in (
        job_status_mod.STATUS_COMPLETE,
        job_status_mod.STATUS_ERROR,
        job_status_mod.STATUS_CANCELLED,
    ):
        return current

    request_cancel(job_id)
    return upsert_job(
        job_id,
        status=job_status_mod.STATUS_CANCELLED,
        progress=float(current.get("progress") or 0.0),
        message="Cancelled by user. Worker slot freed.",
        error_detail="cancelled_by_user",
        claimed_by=None,
        claimed_at=None,
        heartbeat_at=None,
        understanding="skipped",
    )


def list_jobs_for_user(
    user_id: int,
    *,
    limit: int = 50,
    include_terminal: bool = True,
    include_result: bool = False,
) -> List[Dict[str, Any]]:
    """Persistent job history for the signed-in user (all sessions).

    By default skips loading ``result_json`` / heavy payload columns so sidebar
    polls stay cheap. Pass ``include_result=True`` only when the full payload
    is required.
    """
    if not _db_enabled():
        # Fallback: in-memory only
        out = []
        for jid, st in JOB_STATUSES.items():
            if st.get("user_id") is not None and int(st["user_id"]) != int(user_id):
                continue
            if not include_terminal and str(st.get("status")) in (
                job_status_mod.STATUS_COMPLETE,
                job_status_mod.STATUS_ERROR,
                job_status_mod.STATUS_CANCELLED,
            ):
                continue
            row = dict(st)
            if not include_result:
                row.pop("result", None)
                row.pop("understanding", None)
                row.pop("routing_decision", None)
            out.append(row)
        out.sort(key=lambda x: str(x.get("updated_at") or x.get("job_id") or ""), reverse=True)
        return out[: max(1, limit)]

    from sqlalchemy.orm import load_only

    from src.db.models import JobModel
    from src.db.session import get_session

    db = get_session()
    try:
        q = select(JobModel).where(JobModel.user_id == int(user_id))
        if not include_terminal:
            q = q.where(
                JobModel.status.in_(
                    [
                        job_status_mod.STATUS_PENDING,
                        job_status_mod.STATUS_PROCESSING,
                    ]
                )
            )
        if not include_result:
            q = q.options(
                load_only(
                    JobModel.id,
                    JobModel.user_id,
                    JobModel.status,
                    JobModel.progress,
                    JobModel.message,
                    JobModel.filename,
                    JobModel.job_mode,
                    JobModel.claimed_by,
                    JobModel.attempt_count,
                    JobModel.error_detail,
                    JobModel.available_at,
                    JobModel.heartbeat_at,
                    JobModel.created_at,
                    JobModel.updated_at,
                    JobModel.completed_at,
                )
            )
        q = q.order_by(JobModel.created_at.desc()).limit(max(1, min(200, int(limit))))
        rows = db.execute(q).scalars().all()
        return [_row_to_status(r, include_result=include_result) for r in rows]
    finally:
        db.close()


def queue_snapshot_for_user(user_id: int) -> Dict[str, Any]:
    """Worker occupancy + this user's active/queued jobs (for live UI)."""
    workers = list_worker_heartbeats()
    alive = [w for w in workers if w.get("alive")]
    active = list_jobs_for_user(user_id, limit=30, include_terminal=False)
    # Also surface any processing job claimed by a live worker (even other users' —
    # only show filename-safe occupancy flag, not others' content)
    busy_workers = []
    for w in alive:
        meta = w.get("meta") if isinstance(w.get("meta"), dict) else {}
        # meta may use meta_json key depending on serializer
        if not meta:
            meta = w.get("meta_json") if isinstance(w.get("meta_json"), dict) else {}
        cur = meta.get("current_job_id") if isinstance(meta, dict) else None
        busy_workers.append(
            {
                "worker_id": w.get("worker_id"),
                "status": w.get("status"),
                "alive": True,
                "current_job_id": cur,
                "busy": bool(cur) or str(w.get("status") or "") == "busy",
            }
        )
    return {
        "alive_workers": len(alive),
        "workers": busy_workers,
        "worker_busy": any(b.get("busy") for b in busy_workers) or any(
            str(j.get("status")) == job_status_mod.STATUS_PROCESSING for j in active
        ),
        "active_jobs": active,
        "queued_count": sum(
            1 for j in active if str(j.get("status")) == job_status_mod.STATUS_PENDING
        ),
        "processing_count": sum(
            1 for j in active if str(j.get("status")) == job_status_mod.STATUS_PROCESSING
        ),
    }


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
            new_status = str(current["status"])
            # Never let a late heartbeat / progress write reopen a finished job.
            if (
                row.status
                in (
                    job_status_mod.STATUS_COMPLETE,
                    job_status_mod.STATUS_ERROR,
                    job_status_mod.STATUS_CANCELLED,
                )
                and new_status == job_status_mod.STATUS_PROCESSING
            ):
                log.warning(
                    "Job %s: ignoring status downgrade %s → %s (result already terminal)",
                    job_id,
                    row.status,
                    new_status,
                )
            else:
                row.status = new_status
        if "progress" in current and current["progress"] is not None:
            row.progress = float(current["progress"])
        if "message" in current:
            # Keep the terminal completion message if we refused a downgrade.
            if not (
                row.status
                in (
                    job_status_mod.STATUS_COMPLETE,
                    job_status_mod.STATUS_ERROR,
                    job_status_mod.STATUS_CANCELLED,
                )
                and str(current.get("status") or "") == job_status_mod.STATUS_PROCESSING
            ):
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


def _purge_document_artifacts(document_id: str) -> None:
    """Best-effort wipe of RAG sidecars for a document/job id."""
    # Object storage bytes
    try:
        from src.memory import storage as mem_storage
        from src.storage import get_object_storage

        key = mem_storage.get_document_storage_key(document_id)
        if key:
            get_object_storage().delete(key)
    except Exception as e:
        log.warning("Object storage delete failed for %s: %s", document_id, e)

    try:
        from src.memory import storage as mem_storage

        mem_storage.delete_chunks(document_id)
        mem_storage.delete_document_data(document_id)
    except Exception as e:
        log.warning("Document/chunk delete failed for %s: %s", document_id, e)


def delete_job_record(job_id: str) -> bool:
    """Remove job row from DB + process cache (does not wipe document artifacts)."""
    JOB_STATUSES.pop(job_id, None)
    clear_cancel_request(job_id)
    if not _db_enabled():
        return True
    try:
        from src.db.models import JobModel
        from src.db.session import get_session

        db = get_session()
        try:
            row = db.get(JobModel, job_id)
            if row is None:
                return False
            db.delete(row)
            db.commit()
            return True
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    except Exception as e:
        log.warning("delete_job_record failed for %s: %s", job_id, e)
        return False


def purge_job_completely(job_id: str, *, user_id: Optional[int] = None) -> bool:
    """
    Cancel if active, delete document/RAG artifacts, then remove the job row.
    Job id == document id in this product.
    """
    current = get_job(job_id)
    if current is None:
        # Still try artifact cleanup (orphans)
        _purge_document_artifacts(job_id)
        return delete_job_record(job_id)

    if user_id is not None and current.get("user_id") is not None:
        if int(current["user_id"]) != int(user_id):
            raise PermissionError("Not the job owner")

    status = str(current.get("status") or "")
    if status in (job_status_mod.STATUS_PENDING, job_status_mod.STATUS_PROCESSING):
        try:
            cancel_job(job_id, user_id=user_id)
        except Exception as e:
            log.warning("Cancel before purge failed for %s: %s", job_id, e)

    _purge_document_artifacts(job_id)
    return delete_job_record(job_id)


def retain_only_latest_job(
    user_id: int,
    *,
    keep_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Portfolio / single-slot retention: keep only the newest job for this user.
    Deletes older jobs and their document/RAG data.
    """
    jobs = list_jobs_for_user(user_id, limit=200, include_terminal=True)
    if not jobs:
        return {"kept": None, "purged": [], "count_before": 0}

    if keep_job_id:
        keep = str(keep_job_id)
    else:
        keep = str(jobs[0].get("job_id") or "")

    purged: list = []
    for j in jobs:
        jid = str(j.get("job_id") or "")
        if not jid or jid == keep:
            continue
        try:
            purge_job_completely(jid, user_id=user_id)
            purged.append(jid)
        except PermissionError:
            continue
        except Exception as e:
            log.warning("Failed to purge older job %s: %s", jid, e)

    log.info(
        "retain_only_latest_job user=%s keep=%s purged=%s",
        user_id,
        keep,
        len(purged),
    )
    return {"kept": keep or None, "purged": purged, "count_before": len(jobs)}
