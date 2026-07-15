"""
Universal Owner abstraction — authenticated User OR Guest Session.

Pipeline code must not branch on identity; only API ownership checks do.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class OwnerType(str, Enum):
    USER = "user"
    GUEST = "guest"


GUEST_COOKIE_NAME = "ga_guest_session"
GUEST_HEADER_NAME = "X-Guest-Session-Id"
GUEST_INACTIVITY_HOURS = 2
GUEST_MAX_DOCUMENTS = 1
GUEST_MAX_PDF_BYTES = 25 * 1024 * 1024
GUEST_MAX_CHATS = 50
GUEST_CLEANUP_INTERVAL_SEC = 30 * 60


@dataclass(frozen=True)
class Owner:
    owner_type: OwnerType
    owner_id: str
    user_id: Optional[int] = None
    guest_session_id: Optional[str] = None
    anonymous_name: Optional[str] = None
    expires_at: Optional[str] = None
    email: Optional[str] = None
    full_name: Optional[str] = None
    is_active: bool = True

    @property
    def is_guest(self) -> bool:
        return self.owner_type == OwnerType.GUEST

    @property
    def is_user(self) -> bool:
        return self.owner_type == OwnerType.USER

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "owner_type": self.owner_type.value,
            "owner_id": self.owner_id,
            "is_guest": self.is_guest,
            "is_active": self.is_active,
            "user_id": self.user_id,
            "guest_session_id": self.guest_session_id,
            "anonymous_name": self.anonymous_name,
            "expires_at": self.expires_at,
            "email": self.email,
            "full_name": self.full_name,
        }
        # Backward-compat for handlers that still read current_user["id"]
        if self.user_id is not None:
            d["id"] = self.user_id
        return d


def owner_from_user(user: Dict[str, Any]) -> Owner:
    uid = int(user["id"])
    return Owner(
        owner_type=OwnerType.USER,
        owner_id=str(uid),
        user_id=uid,
        email=user.get("email"),
        full_name=user.get("full_name"),
        is_active=bool(user.get("is_active", True)),
    )


def owner_from_guest(session: Dict[str, Any]) -> Owner:
    sid = str(session["session_id"])
    return Owner(
        owner_type=OwnerType.GUEST,
        owner_id=sid,
        guest_session_id=sid,
        anonymous_name=session.get("anonymous_name"),
        expires_at=session.get("expires_at"),
        is_active=str(session.get("status") or "active") == "active",
    )


def stamp_owner_fields(owner: Owner | Dict[str, Any]) -> Dict[str, Any]:
    """Fields to persist on jobs/documents/conversations."""
    if isinstance(owner, dict):
        return {
            "owner_type": owner.get("owner_type") or OwnerType.USER.value,
            "owner_id": str(owner.get("owner_id") or owner.get("id") or ""),
            "user_id": int(owner["id"]) if owner.get("id") is not None else owner.get("user_id"),
        }
    return {
        "owner_type": owner.owner_type.value,
        "owner_id": owner.owner_id,
        "user_id": owner.user_id,
    }


def owners_match(a: Owner | Dict[str, Any], *, owner_type: Optional[str], owner_id: Optional[str], user_id: Optional[int] = None) -> bool:
    """True if resource ownership matches the caller."""
    if isinstance(a, Owner):
        a_type = a.owner_type.value
        a_id = a.owner_id
        a_uid = a.user_id
    else:
        a_type = str(a.get("owner_type") or (OwnerType.USER.value if a.get("id") is not None else ""))
        a_id = str(a.get("owner_id") or a.get("id") or "")
        a_uid = a.get("user_id") if a.get("user_id") is not None else a.get("id")

    if owner_type and owner_id:
        return str(owner_type) == a_type and str(owner_id) == str(a_id)
    # Legacy rows: user_id only
    if user_id is not None and a_uid is not None:
        try:
            return int(user_id) == int(a_uid) and a_type in ("", OwnerType.USER.value)
        except (TypeError, ValueError):
            return False
    return False
