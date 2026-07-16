"""Refresh-token persistence (hashed, rotatable, revocable)."""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from src.core.config import settings
from src.db.models import RefreshTokenModel
from src.db.session import get_session

log = logging.getLogger("db.refresh_tokens")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def hash_token(raw: str) -> str:
    """
    Peppered HMAC-SHA256 of the opaque refresh token.
    DB leak alone is insufficient without the server JWT secret.
    """
    secret = settings.resolved_jwt_secret().encode("utf-8")
    return hmac.new(secret, (raw or "").encode("utf-8"), hashlib.sha256).hexdigest()


def generate_raw_token() -> str:
    return secrets.token_urlsafe(48)


def issue_refresh_token(
    user_id: int,
    *,
    user_agent: Optional[str] = None,
) -> Tuple[str, RefreshTokenModel]:
    """Create a new refresh token. Returns (raw_token, row)."""
    raw = generate_raw_token()
    days = int(getattr(settings, "REFRESH_TOKEN_EXPIRE_DAYS", 14) or 14)
    db = get_session()
    try:
        row = RefreshTokenModel(
            user_id=user_id,
            token_hash=hash_token(raw),
            expires_at=_now() + timedelta(days=days),
            user_agent=(user_agent or "")[:512] or None,
        )
        db.add(row)
        db.commit()
        # Skip db.refresh — callers only need the raw token string; an extra
        # Neon round-trip on every login was adding ~0.5–2s.
        return raw, row
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_valid_token_row(raw: str) -> Optional[RefreshTokenModel]:
    """Return non-revoked, non-expired token row for raw token."""
    th = hash_token(raw)
    db = get_session()
    try:
        row = db.query(RefreshTokenModel).filter(RefreshTokenModel.token_hash == th).first()
        if not row:
            return None
        if row.revoked_at is not None:
            return None
        exp = row.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < _now():
            return None
        # Detach values we need
        db.expunge(row)
        return row
    finally:
        db.close()


def rotate_refresh_token(
    raw: str,
    *,
    user_agent: Optional[str] = None,
) -> Optional[Tuple[str, int]]:
    """
    Rotate: revoke old token, issue new one.
    Returns (new_raw, user_id) or None if invalid/revoked/expired.
    Reuse of an already-rotated token revokes the whole family (theft detection).
    """
    th = hash_token(raw)
    db = get_session()
    try:
        row = db.query(RefreshTokenModel).filter(RefreshTokenModel.token_hash == th).first()
        if not row:
            return None

        # Stolen token reuse: if already revoked via rotation, revoke all for user
        if row.revoked_at is not None and row.replaced_by_hash:
            _revoke_all_for_user(db, row.user_id)
            db.commit()
            log.warning(f"Refresh token reuse detected for user_id={row.user_id}; revoked all")
            return None

        if row.revoked_at is not None:
            return None

        exp = row.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < _now():
            return None

        user_id = row.user_id
        new_raw = generate_raw_token()
        days = int(getattr(settings, "REFRESH_TOKEN_EXPIRE_DAYS", 14) or 14)
        new_row = RefreshTokenModel(
            user_id=user_id,
            token_hash=hash_token(new_raw),
            expires_at=_now() + timedelta(days=days),
            user_agent=(user_agent or row.user_agent or "")[:512] or None,
        )
        db.add(new_row)
        db.flush()
        row.revoked_at = _now()
        row.replaced_by_hash = new_row.token_hash
        db.commit()
        return new_raw, user_id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def revoke_token(raw: str) -> bool:
    th = hash_token(raw)
    db = get_session()
    try:
        row = db.query(RefreshTokenModel).filter(RefreshTokenModel.token_hash == th).first()
        if not row:
            return False
        if row.revoked_at is None:
            row.revoked_at = _now()
            db.commit()
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def revoke_all_for_user(user_id: int) -> int:
    db = get_session()
    try:
        n = _revoke_all_for_user(db, user_id)
        db.commit()
        return n
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _revoke_all_for_user(db, user_id: int) -> int:
    now = _now()
    rows = (
        db.query(RefreshTokenModel)
        .filter(
            RefreshTokenModel.user_id == user_id,
            RefreshTokenModel.revoked_at.is_(None),
        )
        .all()
    )
    for r in rows:
        r.revoked_at = now
    return len(rows)
