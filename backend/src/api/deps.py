"""
Auth dependencies and ownership enforcement.

Supports universal Owner: authenticated User (JWT) OR Guest Session (cookie/header).
JWT always wins when present. Pipeline code does not branch on identity type.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional, Tuple

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.api import auth
from src.core.owner import (
    GUEST_COOKIE_NAME,
    GUEST_HEADER_NAME,
    OwnerType,
    owner_from_guest,
    owner_from_user,
    owners_match,
)
from src.db import guests as guest_store
from src.db import jobs as job_store

log = logging.getLogger("api.deps")

security = HTTPBearer(auto_error=False)

_USER_CACHE_TTL_SEC = 60.0
_user_cache_lock = threading.Lock()
_user_cache: Dict[int, Tuple[float, Dict[str, Any]]] = {}


def seed_user_cache(user: Dict[str, Any]) -> None:
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
    Require a valid Bearer access token (authenticated users only).
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

    from src.memory import storage

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
    if credentials is None or not credentials.credentials:
        return None
    try:
        return get_current_user(credentials)
    except HTTPException:
        return None


def _guest_id_from_request(request: Request) -> Optional[str]:
    # Prefer explicit header (cross-origin / Vercel→Render) over cookie.
    from src.api.input_validation import require_uuid

    raw: Optional[str] = None
    header = request.headers.get(GUEST_HEADER_NAME) or request.headers.get(
        GUEST_HEADER_NAME.lower()
    )
    if header and header.strip():
        raw = header.strip()
    else:
        cookie = request.cookies.get(GUEST_COOKIE_NAME)
        if cookie:
            raw = cookie.strip()
    if not raw:
        return None
    try:
        return require_uuid(raw, field="guest_session_id")
    except ValueError:
        return None


def get_current_owner(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """
    Resolve Owner for business routes.

    Priority: valid JWT user → guest cookie/header → 401.
    """
    if credentials is not None and credentials.credentials:
        try:
            user = get_current_user(credentials)
            return owner_from_user(user).to_dict()
        except HTTPException:
            if credentials.credentials:
                raise

    sid = _guest_id_from_request(request)
    if not sid:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated — sign in or start a guest demo session",
            headers={"WWW-Authenticate": "Bearer"},
        )
    sess = guest_store.touch_guest_session(sid)
    if sess is None:
        raise HTTPException(status_code=401, detail="Guest session not found")
    if str(sess.get("status")) != "active":
        raise HTTPException(status_code=401, detail="Guest session expired")
    return owner_from_guest(sess).to_dict()


def _resource_owner_fields(document_id: str) -> Dict[str, Any]:
    """Resolve owner_type/owner_id from document or job (PK lookup)."""
    fields: Dict[str, Any] = {}
    try:
        from src.db.models import DocumentModel
        from src.db.session import get_session

        db = get_session()
        try:
            doc = db.get(DocumentModel, document_id)
            if doc is not None:
                fields["owner_type"] = getattr(doc, "owner_type", None)
                fields["owner_id"] = getattr(doc, "owner_id", None)
                fields["user_id"] = doc.user_id
        finally:
            db.close()
    except Exception:
        pass
    if fields.get("owner_type") and fields.get("owner_id"):
        return fields
    job = job_store.get_job(document_id, include_result=False)
    if job:
        fields["owner_type"] = job.get("owner_type")
        fields["owner_id"] = job.get("owner_id")
        fields["user_id"] = job.get("user_id")
    return fields


def enforce_owner(owner: Dict[str, Any], resource: Dict[str, Any]) -> None:
    """Raise 403/404 unless resource owner_type+owner_id match the request Owner."""
    if not resource:
        raise HTTPException(status_code=404, detail="Not found")
    ot = resource.get("owner_type")
    oid = resource.get("owner_id")
    if not ot or not oid:
        raise HTTPException(status_code=404, detail="Not found")
    if not owners_match(owner, owner_type=str(ot), owner_id=str(oid)):
        raise HTTPException(status_code=403, detail="Forbidden")


def enforce_job_owner_dict(owner: Dict[str, Any], job_id: str, status: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not status:
        raise HTTPException(status_code=404, detail="Job not found.")
    enforce_owner(owner, status)
    return status


def assert_document_owner_for(owner: Dict[str, Any], document_id: str) -> None:
    fields = _resource_owner_fields(document_id)
    if not fields.get("owner_type") or not fields.get("owner_id"):
        raise HTTPException(status_code=404, detail="Document not found")
    enforce_owner(owner, fields)


def assert_conversation_owner_for(owner: Dict[str, Any], conversation_id: str, document_id: str) -> None:
    """
    Enforce that an existing conversation belongs to the caller.

    Missing conversation → OK (caller may create it).
    Existing conversation → require document match + owner match (never skip).
    Checks DB first, then file-backed MemoryService fallback.
    """
    assert_document_owner_for(owner, document_id)
    if not (conversation_id or "").strip():
        return

    data: Optional[Dict[str, Any]] = None
    try:
        from src.db import conversations as conv_db

        data = conv_db.load_conversation(conversation_id)
    except Exception:
        data = None

    if data is None:
        try:
            from src.memory.service import MemoryService

            state = MemoryService().get_conversation(conversation_id)
            if state is not None:
                payload = state.to_dict()
                # File payloads may carry owner_* alongside state fields.
                data = dict(payload)
        except Exception:
            data = None

    if data is None:
        # Truly new conversation id — create path will stamp ownership.
        return

    if str(data.get("document_id") or "") != str(document_id):
        raise HTTPException(status_code=400, detail="Conversation/document mismatch")
    ot = data.get("owner_type")
    oid = data.get("owner_id")
    if not ot or not oid:
        # Legacy conversation without owner stamp — deny access (fail closed).
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not owners_match(owner, owner_type=str(ot), owner_id=str(oid)):
        raise HTTPException(status_code=403, detail="Forbidden")
