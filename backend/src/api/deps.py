"""
Auth dependencies and ownership enforcement (Phase 1).

Infrastructure only — does not touch AI agents.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.api import auth
from src.db import jobs as job_store
from src.memory import storage

log = logging.getLogger("api.deps")

security = HTTPBearer(auto_error=False)


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

    user = storage.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
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
    job = job_store.get_job(document_id)
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
