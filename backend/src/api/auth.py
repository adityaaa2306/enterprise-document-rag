"""
Authentication utilities: bcrypt passwords, JWT access tokens, refresh rotation.

Security invariants:
- Passwords are bcrypt-hashed (never stored or returned in plaintext).
- Access JWTs are short-lived; refresh tokens expire and rotate.
- JWT signing secrets stay server-side only (never in API responses).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import bcrypt
from jose import JWTError, jwt

from src.core.config import settings
from src.db import refresh_tokens as rt_store

REFRESH_COOKIE_NAME = "refresh_token"

# Precomputed bcrypt hash of "__dummy_password_for_timing__" (cost 12).
# Used to equalize login timing when the email is unknown.
_DUMMY_PASSWORD_HASH = (
    "$2b$12$JBpI4nxNtLKbuBz5RaIX/O.fWkCIje3I6ZAqE1GJDXlCCFBMEC1mC"
)

_PASSWORD_UPPER = re.compile(r"[A-Z]")
_PASSWORD_LOWER = re.compile(r"[a-z]")
_PASSWORD_DIGIT = re.compile(r"[0-9]")


def _bcrypt_rounds() -> int:
    rounds = int(getattr(settings, "BCRYPT_ROUNDS", 12) or 12)
    return max(10, min(rounds, 14))


def _password_bytes(password: str) -> bytes:
    # bcrypt truncates at 72 bytes; enforce explicitly for hash/verify parity.
    return (password or "").encode("utf-8")[:72]


def validate_password_strength(password: str) -> Optional[str]:
    """
    Server-side password policy. Returns an error message, or None if OK.
    Aligns with the signup UI (min 8, upper, lower, digit) and caps length.
    """
    if password is None:
        return "Password is required"
    if len(password) < 8:
        return "Password must be at least 8 characters long"
    # Reject absurd lengths before bcrypt (DoS); bcrypt itself caps at 72 bytes.
    if len(password.encode("utf-8")) > 72:
        return "Password must be at most 72 bytes"
    if not _PASSWORD_UPPER.search(password):
        return "Password must include at least one uppercase letter"
    if not _PASSWORD_LOWER.search(password):
        return "Password must include at least one lowercase letter"
    if not _PASSWORD_DIGIT.search(password):
        return "Password must include at least one number"
    return None


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(
            _password_bytes(plain_password),
            (hashed_password or "").encode("utf-8"),
        )
    except Exception:
        return False


def verify_password_with_dummy(plain_password: str, hashed_password: Optional[str]) -> bool:
    """
    Constant-ish work: if hash is missing, still run bcrypt against a dummy hash
    so unknown-email logins take similar time to wrong-password logins.
    """
    target = hashed_password if hashed_password else _DUMMY_PASSWORD_HASH
    return verify_password(plain_password, target)


def get_password_hash(password: str) -> str:
    err = validate_password_strength(password)
    if err:
        raise ValueError(err)
    return bcrypt.hashpw(_password_bytes(password), bcrypt.gensalt(rounds=_bcrypt_rounds())).decode(
        "utf-8"
    )


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=int(settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update(
        {
            "exp": expire,
            "iat": now,
            "nbf": now,
            "type": "access",
        }
    )
    secret = settings.resolved_jwt_secret()
    return jwt.encode(to_encode, secret, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    try:
        secret = settings.resolved_jwt_secret()
        payload = jwt.decode(
            token,
            secret,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require_exp": True, "require_iat": True},
        )
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
        expires_delta=timedelta(minutes=int(settings.ACCESS_TOKEN_EXPIRE_MINUTES)),
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
        expires_delta=timedelta(minutes=int(settings.ACCESS_TOKEN_EXPIRE_MINUTES)),
    )
    return {
        "access_token": access,
        "refresh_token": new_raw,
        "token_type": "bearer",
        "expires_in": int(settings.ACCESS_TOKEN_EXPIRE_MINUTES) * 60,
        "user_id": user_id,
    }


def logout_refresh(
    refresh_raw: Optional[str],
    *,
    revoke_all: bool = False,
    user_id: Optional[int] = None,
) -> None:
    if revoke_all and user_id is not None:
        rt_store.revoke_all_for_user(user_id)
        return
    if refresh_raw:
        rt_store.revoke_token(refresh_raw)


def cookie_kwargs() -> Dict[str, Any]:
    """kwargs for Response.set_cookie / delete_cookie for refresh token."""
    secure = bool(getattr(settings, "AUTH_COOKIE_SECURE", False))
    if settings.is_production:
        secure = True
    return {
        "key": REFRESH_COOKIE_NAME,
        "httponly": True,
        "secure": secure,
        "samesite": getattr(settings, "AUTH_COOKIE_SAMESITE", "lax") or "lax",
        "path": "/auth",
        "max_age": int(getattr(settings, "REFRESH_TOKEN_EXPIRE_DAYS", 14) or 14) * 86400,
    }


def token_response_payload(pair: Dict[str, Any], *, include_refresh_in_body: bool = True) -> Dict[str, Any]:
    """
    Build public token payload. Never includes signing secrets.
    When cookies carry the refresh token, the body may omit it.
    """
    out = {
        "access_token": pair["access_token"],
        "token_type": pair.get("token_type") or "bearer",
        "expires_in": pair.get("expires_in"),
    }
    if include_refresh_in_body and pair.get("refresh_token"):
        out["refresh_token"] = pair["refresh_token"]
    return out
