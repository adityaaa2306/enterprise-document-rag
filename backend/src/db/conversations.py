"""Conversation persistence (DB-backed when PERSIST_CONVERSATIONS_TO_DB).

Business ownership uses owner_type + owner_id (Owner abstraction).
user_id remains an optional identity column for authenticated users.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from src.core.config import settings

log = logging.getLogger("db.conversations")


def _db_enabled() -> bool:
    return bool(getattr(settings, "PERSIST_CONVERSATIONS_TO_DB", True))


def _ttl() -> timedelta:
    hours = float(getattr(settings, "CONVERSATION_TTL_HOURS", 24.0) or 24.0)
    return timedelta(hours=hours)


def _to_aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def load_conversation(conversation_id: str) -> Optional[Dict[str, Any]]:
    if not _db_enabled():
        return None
    from src.db.models import ConversationModel, ConversationTurnModel
    from src.db.session import get_session

    db = get_session()
    try:
        row = db.get(ConversationModel, conversation_id)
        if not row:
            return None
        now = datetime.now(timezone.utc)
        expires = _to_aware(row.expires_at)
        if expires and expires < now:
            db.delete(row)
            db.commit()
            return None
        turns = []
        for t in row.turns:
            turns.append(
                {
                    "role": t.role,
                    "content": t.content,
                    "entities": t.entities or [],
                    "meta": t.meta or {},
                    "ts": (_to_aware(t.ts) or now).timestamp(),
                }
            )
        return {
            "conversation_id": row.id,
            "document_id": row.document_id,
            "user_id": row.user_id,
            "owner_type": getattr(row, "owner_type", None),
            "owner_id": getattr(row, "owner_id", None),
            "turns": turns,
            "created_at": (_to_aware(row.created_at) or now).timestamp(),
            "updated_at": (_to_aware(row.updated_at) or now).timestamp(),
        }
    except Exception as e:
        log.error(f"load_conversation failed: {e}")
        return None
    finally:
        db.close()


def save_conversation_state(
    conversation_id: str,
    document_id: str,
    turns: List[Dict[str, Any]],
    *,
    owner_type: str,
    owner_id: str,
    user_id: Optional[int] = None,
    created_at: Optional[float] = None,
) -> bool:
    if not _db_enabled():
        return False
    if not owner_type or not owner_id:
        log.error("save_conversation_state requires owner_type and owner_id")
        return False
    from src.db.models import ConversationModel, ConversationTurnModel
    from src.db.session import get_session

    now = datetime.now(timezone.utc)
    max_turns = int(getattr(settings, "CONVERSATION_MAX_TURNS", 40) or 40)
    trimmed = turns[-max_turns:] if len(turns) > max_turns else turns

    db = get_session()
    try:
        row = db.get(ConversationModel, conversation_id)
        if row is None:
            row = ConversationModel(
                id=conversation_id,
                document_id=document_id,
                user_id=user_id,
                owner_type=str(owner_type),
                owner_id=str(owner_id),
                created_at=datetime.fromtimestamp(created_at, tz=timezone.utc) if created_at else now,
                updated_at=now,
                expires_at=now + _ttl(),
            )
            db.add(row)
        else:
            # Never reassign ownership — IDOR defense in depth.
            existing_ot = getattr(row, "owner_type", None)
            existing_oid = getattr(row, "owner_id", None)
            if existing_ot and existing_oid:
                if str(existing_ot) != str(owner_type) or str(existing_oid) != str(owner_id):
                    log.warning(
                        "save_conversation_state ownership mismatch for %s",
                        conversation_id,
                    )
                    raise PermissionError("Conversation ownership mismatch")
            if str(row.document_id) != str(document_id):
                raise PermissionError("Conversation/document mismatch")
            if not existing_ot or not existing_oid:
                row.owner_type = str(owner_type)
                row.owner_id = str(owner_id)
            if user_id is not None and row.user_id is None:
                row.user_id = user_id
            row.updated_at = now
            row.expires_at = now + _ttl()
            db.query(ConversationTurnModel).filter(
                ConversationTurnModel.conversation_id == conversation_id
            ).delete()

        for t in trimmed:
            ts_raw = t.get("ts")
            if isinstance(ts_raw, (int, float)):
                ts = datetime.fromtimestamp(float(ts_raw), tz=timezone.utc)
            else:
                ts = now
            db.add(
                ConversationTurnModel(
                    conversation_id=conversation_id,
                    role=str(t.get("role") or "user"),
                    content=str(t.get("content") or ""),
                    entities=list(t.get("entities") or []),
                    meta=dict(t.get("meta") or {}),
                    ts=ts,
                )
            )
        db.commit()
        return True
    except PermissionError:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        log.error(f"save_conversation_state failed: {e}")
        return False
    finally:
        db.close()


def delete_conversation(conversation_id: str) -> None:
    if not _db_enabled():
        return
    from src.db.models import ConversationModel
    from src.db.session import get_session

    db = get_session()
    try:
        row = db.get(ConversationModel, conversation_id)
        if row:
            db.delete(row)
            db.commit()
    except Exception as e:
        db.rollback()
        log.warning(f"delete_conversation failed: {e}")
    finally:
        db.close()


def clear_for_document(document_id: str) -> int:
    """Delete conversations for a document (PK-scoped cleanup after Owner-checked purge)."""
    if not _db_enabled():
        return 0
    from src.db.models import ConversationModel
    from src.db.session import get_session

    db = get_session()
    try:
        rows = db.query(ConversationModel).filter(ConversationModel.document_id == document_id).all()
        n = len(rows)
        for r in rows:
            db.delete(r)
        db.commit()
        return n
    except Exception as e:
        db.rollback()
        log.warning(f"clear_for_document failed: {e}")
        return 0
    finally:
        db.close()


def clear_for_owner(*, owner_type: str, owner_id: str) -> int:
    """Delete-many conversations for an Owner (guest cleanup / wipe)."""
    if not _db_enabled():
        return 0
    from src.db.models import ConversationModel
    from src.db.session import get_session

    db = get_session()
    try:
        rows = (
            db.query(ConversationModel)
            .filter(
                ConversationModel.owner_type == str(owner_type),
                ConversationModel.owner_id == str(owner_id),
            )
            .all()
        )
        n = len(rows)
        for r in rows:
            db.delete(r)
        db.commit()
        return n
    except Exception as e:
        db.rollback()
        log.warning(f"clear_for_owner failed: {e}")
        return 0
    finally:
        db.close()
