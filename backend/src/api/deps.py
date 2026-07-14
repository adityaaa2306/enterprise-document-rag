"""
Auth dependencies and ownership enforcement (Phase 1).

Infrastructure only — does not touch AI agents.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional, Tuple

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.api import auth
from src.db import jobs as job_store
from src.memory import storage

log = logging.getLogger("api.deps")

security = HTTPBearer(auto_error=False)

# Short TTL cache: parallel /jobs + /queue + /job-status each called get_user_by_id
# against remote Neon (~0.5–2s RTT). Cache collapses that to one lookup per window.
_USER_CACHE_TTL_SEC = 60.0
_user_cache_lock = threading.Lock()
_user_cache: Dict[int, Tuple[float, Dict[str, Any]]] = {}


def seed_user_cache(user: Dict[str, Any]) -> None:
    """Populate auth cache after login/register so the next request skips Neon."""
    try:
        uid = int(user["id"])
    except (KeyError, TypeError, ValueError):
        return
    with _user_cache_lock:
        _user_cache[uid] = (time.monotonic(), dict(user))


def invalidate_user_cache(user_id: Optional[int] = None) -> None:
    with _user_cache_lock:
        if user_id is None:
            _user_cache.clear()
        else:
            _user_cache.pop(int(user_id), None)


def _cached_user(user_id: int) -> Optional[Dict[str, Any]]:
    now = time.monotonic()
    with _user_cache_lock:
        hit = _user_cache.get(user_id)
        if hit and now - hit[0] < _USER_CACHE_TTL_SEC:
            return dict(hit[1])
    return None


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """
    Require a valid Bearer access token.
    Verifies: JWT valid, type=access, user exists, user is_active.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    payload = auth.decode_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    sub = payload.get("sub")
    if sub is None:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    try:
        user_id = int(sub)
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token subject")

    user = _cached_user(user_id)
    if user is None:
        user = storage.get_user_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="User not found")
        seed_user_cache(user)
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account is inactive")
    return user


def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[Dict[str, Any]]:
    """Optional auth (unused for business routes; kept for health/compat)."""
    if credentials is None or not credentials.credentials:
        return None
    try:
        return get_current_user(credentials)
    except HTTPException:
        return None


def _owner_id_for_document(document_id: str) -> Optional[int]:
    """Resolve owning user_id from document row or job row."""
    uid = storage.get_document_user_id(document_id)
    if uid is not None:
        return int(uid)
    job = job_store.get_job(document_id, include_result=False)
    if job and job.get("user_id") is not None:
        try:
            return int(job["user_id"])
        except (TypeError, ValueError):
            return None
    return None


def require_document_owner(
    document_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Ensure current user owns the document/job identified by document_id."""
    owner = _owner_id_for_document(document_id)
    if owner is None:
        # Do not leak whether the id exists in other tenants' data
        raise HTTPException(status_code=404, detail="Document not found")
    if int(owner) != int(current_user["id"]):
        raise HTTPException(status_code=403, detail="Forbidden")
    return current_user


def require_job_owner(
    job_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Jobs use the same UUID as document_id."""
    return require_document_owner(job_id, current_user)


def assert_document_owner(user_id: int, document_id: str) -> None:
    """Imperative ownership check (for handlers that already have user)."""
    owner = _owner_id_for_document(document_id)
    if owner is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if int(owner) != int(user_id):
        raise HTTPException(status_code=403, detail="Forbidden")


def enforce_job_owner(
    user_id: int,
    job_id: str,
    status: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Ownership check using an already-loaded job row when possible.

    Avoids the previous pattern of assert_document_owner (extra Neon round-trips)
    followed by a second get_job for the same id.
    """
    if not status:
        raise HTTPException(status_code=404, detail="Job not found.")
    owner = status.get("user_id")
    if owner is not None:
        try:
            if int(owner) != int(user_id):
                raise HTTPException(status_code=403, detail="Forbidden")
        except (TypeError, ValueError):
            raise HTTPException(status_code=403, detail="Forbidden")
        return status
    # Legacy rows without jobs.user_id — fall back to documents table.
    assert_document_owner(user_id, job_id)
    return status


def assert_conversation_owner(user_id: int, conversation_id: str, document_id: str) -> None:
    """Conversation must belong to user and document must be owned."""
    assert_document_owner(user_id, document_id)
    from src.db import conversations as conv_db

    data = conv_db.load_conversation(conversation_id)
    if data is None:
        return  # new conversation will be created
    if data.get("document_id") != document_id:
        raise HTTPException(status_code=400, detail="Conversation/document mismatch")
    conv_uid = data.get("user_id")
    if conv_uid is not None and int(conv_uid) != int(user_id):
        raise HTTPException(status_code=403, detail="Forbidden")
