"""
Guest session persistence and lifecycle (create / touch / expire / cleanup / upgrade).
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from src.core.owner import (
    GUEST_CLEANUP_INTERVAL_SEC,
    GUEST_INACTIVITY_HOURS,
    OwnerType,
)

log = logging.getLogger("db.guests")

_cleanup_lock = threading.Lock()
_cleanup_started = False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _hash_optional(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:32]


def _anonymous_name() -> str:
    return f"Guest-{secrets.token_hex(2).upper()}"


def create_guest_session(
    *,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Dict[str, Any]:
    from src.db.models import GuestSessionModel
    from src.db.session import get_session

    sid = str(uuid.uuid4())
    now = _now()
    expires = now + timedelta(hours=GUEST_INACTIVITY_HOURS)
    row = GuestSessionModel(
        session_id=sid,
        anonymous_name=_anonymous_name(),
        status="active",
        created_at=now,
        expires_at=expires,
        last_activity=now,
        ip_hash=_hash_optional(ip),
        user_agent_hash=_hash_optional(user_agent),
        chat_count=0,
    )
    db = get_session()
    try:
        db.add(row)
        db.commit()
        db.refresh(row)
        return _row_to_dict(row)
    finally:
        db.close()


def get_guest_session(session_id: str) -> Optional[Dict[str, Any]]:
    from src.db.models import GuestSessionModel
    from src.db.session import get_session

    if not session_id:
        return None
    db = get_session()
    try:
        row = db.get(GuestSessionModel, session_id)
        if row is None:
            return None
        return _row_to_dict(row)
    finally:
        db.close()


def touch_guest_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Sliding expiration — refresh last_activity + expires_at if still active."""
    from src.db.models import GuestSessionModel
    from src.db.session import get_session

    db = get_session()
    try:
        row = db.get(GuestSessionModel, session_id)
        if row is None:
            return None
        now = _now()
        exp = row.expires_at
        if exp is not None and exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if str(row.status) != "active" or (exp is not None and exp < now):
            row.status = "expired"
            db.commit()
            return _row_to_dict(row)
        row.last_activity = now
        row.expires_at = now + timedelta(hours=GUEST_INACTIVITY_HOURS)
        db.commit()
        db.refresh(row)
        return _row_to_dict(row)
    finally:
        db.close()


def increment_guest_chat_count(session_id: str) -> int:
    from src.db.models import GuestSessionModel
    from src.db.session import get_session

    db = get_session()
    try:
        row = db.get(GuestSessionModel, session_id)
        if row is None:
            return 0
        row.chat_count = int(row.chat_count or 0) + 1
        db.commit()
        return int(row.chat_count)
    finally:
        db.close()


def get_guest_chat_count(session_id: str) -> int:
    sess = get_guest_session(session_id)
    if not sess:
        return 0
    return int(sess.get("chat_count") or 0)


def list_expired_sessions(*, limit: int = 100) -> List[Dict[str, Any]]:
    """
    Candidates for purge: expired (by status or clock) AND no in-flight jobs.

    Exact filter (SQLAlchemy → SQL)::

        guest_sessions.status NOT IN ('purged', 'upgraded')
        AND (guest_sessions.status = 'expired' OR guest_sessions.expires_at < :now)
        AND NOT EXISTS (
          SELECT 1 FROM jobs
          WHERE jobs.owner_type = 'guest'
            AND jobs.owner_id = guest_sessions.session_id
            AND jobs.status IN ('pending', 'processing')
        )

    Active guests (status=active AND expires_at >= now) are never selected.
    Guests with queued/running jobs are deferred until the job finishes (or fails).
    """
    from sqlalchemy import and_, exists, not_, or_, select

    from src.core import job_status as job_status_mod
    from src.db.models import GuestSessionModel, JobModel
    from src.db.session import get_session

    now = _now()
    db = get_session()
    try:
        running_job = exists(
            select(1).where(
                and_(
                    JobModel.owner_type == OwnerType.GUEST.value,
                    JobModel.owner_id == GuestSessionModel.session_id,
                    JobModel.status.in_(
                        (
                            job_status_mod.STATUS_PENDING,
                            job_status_mod.STATUS_PROCESSING,
                        )
                    ),
                )
            )
        )
        q = (
            select(GuestSessionModel)
            .where(
                GuestSessionModel.status.notin_(("purged", "upgraded")),
                or_(
                    GuestSessionModel.status == "expired",
                    GuestSessionModel.expires_at < now,
                ),
                not_(running_job),
            )
            .limit(limit)
        )
        rows = list(db.scalars(q).all())
        for row in rows:
            if str(row.status) == "active":
                row.status = "expired"
        db.commit()
        return [_row_to_dict(r) for r in rows]
    finally:
        db.close()


def guest_has_running_jobs(session_id: str) -> bool:
    """True if guest still has pending or processing jobs."""
    from sqlalchemy import select

    from src.core import job_status as job_status_mod
    from src.db.models import JobModel
    from src.db.session import get_session

    db = get_session()
    try:
        row = db.execute(
            select(JobModel.id)
            .where(
                JobModel.owner_type == OwnerType.GUEST.value,
                JobModel.owner_id == session_id,
                JobModel.status.in_(
                    (
                        job_status_mod.STATUS_PENDING,
                        job_status_mod.STATUS_PROCESSING,
                    )
                ),
            )
            .limit(1)
        ).first()
        return row is not None
    finally:
        db.close()


def purge_guest_resources(session_id: str) -> Dict[str, Any]:
    """
    Delete guest-owned jobs, documents, conversations, object storage, embeddings.
    Does not touch shared telemetry aggregates.
    """
    from sqlalchemy import select

    from src.db import conversations as conv_db
    from src.db import jobs as job_store
    from src.db.models import ConversationModel, DocumentModel, GuestSessionModel, JobModel
    from src.db.session import get_session
    from src.memory import storage

    report: Dict[str, Any] = {"session_id": session_id, "jobs": 0, "documents": 0, "conversations": 0}
    db = get_session()
    try:
        jobs = list(
            db.scalars(
                select(JobModel).where(
                    JobModel.owner_type == OwnerType.GUEST.value,
                    JobModel.owner_id == session_id,
                )
            ).all()
        )
        job_ids = [j.id for j in jobs]
        docs = list(
            db.scalars(
                select(DocumentModel).where(
                    DocumentModel.owner_type == OwnerType.GUEST.value,
                    DocumentModel.owner_id == session_id,
                )
            ).all()
        )
        doc_ids = [d.id for d in docs]
        convs = list(
            db.scalars(
                select(ConversationModel).where(
                    ConversationModel.owner_type == OwnerType.GUEST.value,
                    ConversationModel.owner_id == session_id,
                )
            ).all()
        )
    finally:
        db.close()

    for jid in job_ids:
        try:
            job_store.purge_job_completely(jid)
            report["jobs"] += 1
        except Exception as e:
            log.warning("purge guest job %s: %s", jid, e)

    for did in set(doc_ids) | set(job_ids):
        try:
            storage.delete_chunks(did)
        except Exception:
            pass
        try:
            from src.memory import chroma as chroma_mod

            if hasattr(chroma_mod, "delete_document"):
                chroma_mod.delete_document(did)
        except Exception:
            pass
        try:
            db = get_session()
            try:
                doc = db.get(DocumentModel, did)
                if doc is not None:
                    key = getattr(doc, "storage_key", None)
                    if key:
                        try:
                            from src.storage.factory import get_object_storage

                            get_object_storage().delete(key)
                        except Exception:
                            pass
                    db.delete(doc)
                    db.commit()
                    report["documents"] += 1
            finally:
                db.close()
        except Exception as e:
            log.warning("purge guest doc %s: %s", did, e)

    for conv in convs:
        try:
            if hasattr(conv_db, "delete_conversation"):
                conv_db.delete_conversation(conv.id)
            else:
                db = get_session()
                try:
                    row = db.get(ConversationModel, conv.id)
                    if row:
                        db.delete(row)
                        db.commit()
                finally:
                    db.close()
            report["conversations"] += 1
        except Exception as e:
            log.warning("purge guest conv %s: %s", conv.id, e)

    db = get_session()
    try:
        row = db.get(GuestSessionModel, session_id)
        if row:
            row.status = "purged"
            db.commit()
    finally:
        db.close()
    return report


def transfer_guest_to_user(session_id: str, user_id: int) -> Dict[str, Any]:
    """Reassign all guest-owned resources to an authenticated user (no recompute).

    Only sessions with status=active are transferable (prevents claiming
    expired/upgraded/purged session IDs).
    """
    from sqlalchemy import update

    from src.db.models import ConversationModel, DocumentModel, GuestSessionModel, JobModel
    from src.db.session import get_session

    db = get_session()
    moved = {"jobs": 0, "documents": 0, "conversations": 0}
    try:
        row = db.get(GuestSessionModel, session_id)
        if row is None or str(row.status or "") != "active":
            return {"ok": False, "error": "Guest session not found or not active"}
        for Model, key in (
            (JobModel, "jobs"),
            (DocumentModel, "documents"),
            (ConversationModel, "conversations"),
        ):
            result = db.execute(
                update(Model)
                .where(
                    Model.owner_type == OwnerType.GUEST.value,
                    Model.owner_id == session_id,
                )
                .values(
                    owner_type=OwnerType.USER.value,
                    owner_id=str(user_id),
                    user_id=int(user_id),
                )
            )
            moved[key] = int(result.rowcount or 0)
        row.status = "upgraded"
        row.upgraded_user_id = int(user_id)
        db.commit()
        return {"ok": True, "session_id": session_id, "user_id": user_id, **moved}
    except Exception as e:
        db.rollback()
        log.exception("transfer_guest_to_user failed: %s", e)
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def cleanup_expired_guests() -> Dict[str, Any]:
    expired = list_expired_sessions(limit=200)
    reports = []
    skipped_running = 0
    for sess in expired:
        sid = sess["session_id"]
        if sess.get("status") == "purged":
            continue
        # Defense in depth: re-check in case a job started after the SELECT.
        if guest_has_running_jobs(sid):
            skipped_running += 1
            log.info("Guest cleanup deferred (running job): %s", sid)
            continue
        reports.append(purge_guest_resources(sid))
    return {
        "cleaned": len(reports),
        "skipped_running": skipped_running,
        "details": reports,
    }


def ensure_guest_cleanup_loop() -> None:
    """Start background cleanup every 30 minutes (idempotent)."""
    global _cleanup_started
    with _cleanup_lock:
        if _cleanup_started:
            return
        _cleanup_started = True

    def _loop() -> None:
        while True:
            try:
                time.sleep(GUEST_CLEANUP_INTERVAL_SEC)
                report = cleanup_expired_guests()
                if report.get("cleaned"):
                    log.info("Guest cleanup: %s", report)
            except Exception as e:
                log.warning("Guest cleanup loop error: %s", e)

    threading.Thread(target=_loop, name="guest-cleanup", daemon=True).start()
    log.info("Guest cleanup loop started (every %ss)", GUEST_CLEANUP_INTERVAL_SEC)


def _row_to_dict(row: Any) -> Dict[str, Any]:
    return {
        "session_id": row.session_id,
        "anonymous_name": row.anonymous_name,
        "status": row.status,
        "created_at": _iso(row.created_at),
        "expires_at": _iso(row.expires_at),
        "last_activity": _iso(row.last_activity),
        "chat_count": int(row.chat_count or 0),
        "upgraded_user_id": getattr(row, "upgraded_user_id", None),
    }
