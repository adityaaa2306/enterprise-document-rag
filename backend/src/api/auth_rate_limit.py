"""
Authentication rate limits (login / register / refresh / guest).

Uses the shared sliding-window limiter from ``abuse_protection``.
"""
from __future__ import annotations

from typing import Optional

from src.api.abuse_protection import (
    SlidingWindowLimiter,
    client_ip,
    get_abuse_limiter,
)

# Backward-compatible aliases
AuthRateLimiter = SlidingWindowLimiter


def get_auth_rate_limiter() -> SlidingWindowLimiter:
    return get_abuse_limiter()


def enforce_auth_rate_limit(
    request,
    *,
    action: str,
    identity: Optional[str] = None,
) -> None:
    """
    Raise HTTPException 429 when over limit.

    Keys:
      - always: ``{action}:ip:{ip}``
      - optional: ``{action}:id:{identity}`` (e.g. email)
    """
    from fastapi import HTTPException

    from src.core.config import settings

    limits = {
        "login": (
            int(getattr(settings, "AUTH_LOGIN_RATE_LIMIT", 10) or 10),
            float(getattr(settings, "AUTH_LOGIN_RATE_WINDOW_SEC", 900) or 900),
        ),
        "register": (
            int(getattr(settings, "AUTH_REGISTER_RATE_LIMIT", 5) or 5),
            float(getattr(settings, "AUTH_REGISTER_RATE_WINDOW_SEC", 3600) or 3600),
        ),
        "refresh": (
            int(getattr(settings, "AUTH_REFRESH_RATE_LIMIT", 60) or 60),
            float(getattr(settings, "AUTH_REFRESH_RATE_WINDOW_SEC", 900) or 900),
        ),
        "guest": (
            int(getattr(settings, "AUTH_GUEST_RATE_LIMIT", 30) or 30),
            float(getattr(settings, "AUTH_GUEST_RATE_WINDOW_SEC", 3600) or 3600),
        ),
    }
    limit, window = limits.get(action, (20, 900.0))
    ip = client_ip(request)
    limiter = get_abuse_limiter()

    allowed, retry, _rem = limiter.check(
        f"{action}:ip:{ip}", limit=limit, window_sec=window
    )
    if not allowed:
        try:
            from src.api.security_audit import log_unusual_traffic

            log_unusual_traffic(
                "auth_rate_limited",
                ip=ip,
                detail=f"action={action}",
            )
        except Exception:
            pass
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Please try again later.",
            headers={"Retry-After": str(max(1, int(retry)))},
        )

    if identity:
        id_limit = max(3, limit // 2)
        allowed_id, retry_id, _rem = limiter.check(
            f"{action}:id:{identity}",
            limit=id_limit,
            window_sec=window,
        )
        if not allowed_id:
            try:
                from src.api.security_audit import log_unusual_traffic

                log_unusual_traffic(
                    "auth_rate_limited",
                    ip=ip,
                    detail=f"action={action} identity",
                )
            except Exception:
                pass
            raise HTTPException(
                status_code=429,
                detail="Too many attempts. Please try again later.",
                headers={"Retry-After": str(max(1, int(retry_id)))},
            )
