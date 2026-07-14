"""
Authentication utilities: bcrypt passwords, JWT access tokens, refresh rotation.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import bcrypt
from jose import JWTError, jwt

from src.core.config import settings
from src.db import refresh_tokens as rt_store

REFRESH_COOKIE_NAME = "refresh_token"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception:
        return False


# Cost 10 ≈ 70ms verify on typical hardware; default 12 ≈ 280ms+.
# Existing $2b$12$ hashes still verify; new signups use 10.
_BCRYPT_ROUNDS = 10


def get_password_hash(password: str) -> str:
    # bcrypt truncates at 72 bytes; enforce explicitly for clarity
    raw = password.encode("utf-8")[:72]
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode("utf-8")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    to_encode.update({
        "exp": expire,
        "type": "access",
        "iat": datetime.now(timezone.utc),
    })
    secret = settings.resolved_jwt_secret()
    return jwt.encode(to_encode, secret, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    try:
        secret = settings.resolved_jwt_secret()
        payload = jwt.decode(token, secret, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") and payload.get("type") != "access":
            return None
        return payload
    except JWTError:
        return None


def issue_token_pair(
    user_id: int,
    *,
    user_agent: Optional[str] = None,
) -> Dict[str, Any]:
    """Issue access JWT + opaque refresh token (stored hashed)."""
    access = create_access_token(
        data={"sub": str(user_id)},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    refresh_raw, _ = rt_store.issue_refresh_token(user_id, user_agent=user_agent)
    return {
        "access_token": access,
        "refresh_token": refresh_raw,
        "token_type": "bearer",
        "expires_in": int(settings.ACCESS_TOKEN_EXPIRE_MINUTES) * 60,
    }


def rotate_token_pair(
    refresh_raw: str,
    *,
    user_agent: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    rotated = rt_store.rotate_refresh_token(refresh_raw, user_agent=user_agent)
    if not rotated:
        return None
    new_raw, user_id = rotated
    access = create_access_token(
        data={"sub": str(user_id)},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return {
        "access_token": access,
        "refresh_token": new_raw,
        "token_type": "bearer",
        "expires_in": int(settings.ACCESS_TOKEN_EXPIRE_MINUTES) * 60,
        "user_id": user_id,
    }


def logout_refresh(refresh_raw: Optional[str], *, revoke_all: bool = False, user_id: Optional[int] = None) -> None:
    if revoke_all and user_id is not None:
        rt_store.revoke_all_for_user(user_id)
        return
    if refresh_raw:
        rt_store.revoke_token(refresh_raw)


def cookie_kwargs() -> Dict[str, Any]:
    """kwargs for Response.set_cookie / delete_cookie for refresh token."""
    return {
        "key": REFRESH_COOKIE_NAME,
        "httponly": True,
        "secure": bool(getattr(settings, "AUTH_COOKIE_SECURE", False)),
        "samesite": getattr(settings, "AUTH_COOKIE_SAMESITE", "lax") or "lax",
        "path": "/auth",
        "max_age": int(getattr(settings, "REFRESH_TOKEN_EXPIRE_DAYS", 14) or 14) * 86400,
    }
