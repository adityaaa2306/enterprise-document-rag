"""
Application abuse protection: sliding-window rate limits + bot heuristics.

Covers:
- login / register / refresh / guest (via enforce_auth_rate_limit)
- general API traffic
- AI generation (summarize, RAG, chat)
- scrape-prone list/poll endpoints

In-process limits are suitable for single-instance / small fleets.
Use a shared store (Redis) when horizontally scaling the API widely.
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from collections import defaultdict, deque
from typing import Callable, Deque, Dict, Optional, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

log = logging.getLogger("security.abuse")

# Paths that must never be rate-limited (probes / root).
_EXEMPT_PATHS = frozenset({"/", "/api/health", "/api/ready", "/api/worker/health"})

# AI / generation endpoints (expensive).
_AI_EXACT = frozenset(
    {
        "/summarize",
        "/rag-query",
        "/rag-query/stream",
        "/chat",
    }
)

# List / poll endpoints often hit by scrapers.
_SCRAPE_EXACT = frozenset(
    {
        "/documents",
        "/jobs",
        "/dashboard-stats",
        "/queue",
    }
)

_BOT_UA_RE = re.compile(
    r"(python-requests|httpx|scrapy|curl/|wget|go-http-client|libwww-perl|"
    r"java/|php/|node-fetch|axios/|postmanruntime|bot|spider|crawler|scraper)",
    re.I,
)


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def check(
        self,
        key: str,
        *,
        limit: int,
        window_sec: float,
    ) -> Tuple[bool, float, int]:
        """
        Returns (allowed, retry_after_sec, remaining_after_this_call).
        On deny, does not record a hit.
        """
        if limit <= 0 or window_sec <= 0:
            return True, 0.0, limit
        now = time.monotonic()
        cutoff = now - float(window_sec)
        with self._lock:
            q = self._hits[key]
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= int(limit):
                retry = max(0.0, float(window_sec) - (now - q[0]))
                return False, retry, 0
            q.append(now)
            remaining = max(0, int(limit) - len(q))
            return True, 0.0, remaining


_limiter = SlidingWindowLimiter()


def get_abuse_limiter() -> SlidingWindowLimiter:
    return _limiter


def client_ip(request: Request) -> str:
    """Best-effort client IP (honors first X-Forwarded-For hop when present)."""
    try:
        from src.core.config import settings

        if bool(getattr(settings, "TRUST_PROXY_HEADERS", True)):
            xff = request.headers.get("x-forwarded-for") or request.headers.get(
                "X-Forwarded-For"
            )
            if xff:
                return str(xff).split(",")[0].strip() or "unknown"
        if request.client and request.client.host:
            return str(request.client.host)
    except Exception:
        pass
    return "unknown"


def _identity_key(request: Request) -> str:
    """Stable secondary key from bearer / guest header (not the secret itself)."""
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer ") and len(auth) > 20:
        raw = auth.split(" ", 1)[1].strip()
        return "tok:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    guest = request.headers.get("x-guest-session-id") or request.headers.get(
        "X-Guest-Session-Id"
    )
    if guest and guest.strip():
        return "guest:" + hashlib.sha256(guest.strip().encode("utf-8")).hexdigest()[:16]
    return "anon"


def _is_bot_client(request: Request) -> bool:
    from src.core.config import settings

    if not bool(getattr(settings, "ABUSE_BLOCK_BOT_USER_AGENTS", True)):
        return False
    ua = (request.headers.get("user-agent") or "").strip()
    if not ua:
        return bool(getattr(settings, "ABUSE_BLOCK_EMPTY_USER_AGENT", True))
    return bool(_BOT_UA_RE.search(ua))


def classify_request(path: str, method: str) -> str:
    """
    Return bucket: exempt | auth | ai | scrape | api
    """
    p = path.rstrip("/") or "/"
    if p in _EXEMPT_PATHS or path in _EXEMPT_PATHS:
        return "exempt"
    if path.startswith("/auth/") or path.startswith("/guest/"):
        return "auth"
    if path in _AI_EXACT or p in _AI_EXACT:
        return "ai"
    if path in _SCRAPE_EXACT or p in _SCRAPE_EXACT:
        return "scrape"
    if method.upper() == "GET" and (
        path.startswith("/documents/")
        or path.startswith("/job-status/")
        or path.startswith("/job-result/")
        or path.startswith("/job-events/")
    ):
        return "scrape"
    return "api"


def _bucket_limits(bucket: str, *, bot: bool, guest: bool) -> Tuple[int, float]:
    from src.core.config import settings

    if bucket == "ai":
        if guest:
            limit = int(getattr(settings, "AI_RATE_LIMIT_GUEST", 10) or 10)
        else:
            limit = int(getattr(settings, "AI_RATE_LIMIT", 20) or 20)
        window = float(getattr(settings, "AI_RATE_WINDOW_SEC", 60) or 60)
    elif bucket == "scrape":
        limit = int(getattr(settings, "SCRAPE_RATE_LIMIT", 60) or 60)
        window = float(getattr(settings, "SCRAPE_RATE_WINDOW_SEC", 60) or 60)
    elif bucket == "auth":
        # Light middleware cap; handlers enforce tighter action-specific limits.
        limit = int(getattr(settings, "AUTH_IP_RATE_LIMIT", 40) or 40)
        window = float(getattr(settings, "AUTH_IP_RATE_WINDOW_SEC", 60) or 60)
    else:
        limit = int(getattr(settings, "API_RATE_LIMIT", 120) or 120)
        window = float(getattr(settings, "API_RATE_WINDOW_SEC", 60) or 60)

    if bot:
        # Automated clients get a tighter ceiling.
        factor = float(getattr(settings, "ABUSE_BOT_LIMIT_FACTOR", 0.25) or 0.25)
        limit = max(1, int(limit * factor))
    return limit, window


def enforce_rate_limit(
    request: Request,
    *,
    bucket: str,
    identity: Optional[str] = None,
) -> None:
    """Raise HTTPException 429 when over limit (for use inside route handlers)."""
    from fastapi import HTTPException

    from src.core.config import settings

    if not bool(getattr(settings, "ABUSE_PROTECTION_ENABLED", True)):
        return
    if bucket == "exempt":
        return

    ip = client_ip(request)
    bot = _is_bot_client(request)
    guest = bool(
        request.headers.get("x-guest-session-id")
        or request.headers.get("X-Guest-Session-Id")
    ) and not (request.headers.get("authorization") or "").lower().startswith("bearer ")
    limit, window = _bucket_limits(bucket, bot=bot, guest=guest)
    limiter = get_abuse_limiter()

    keys = [f"{bucket}:ip:{ip}"]
    if identity:
        keys.append(f"{bucket}:id:{identity}")
    else:
        keys.append(f"{bucket}:id:{_identity_key(request)}")

    for key in keys:
        allowed, retry, _rem = limiter.check(key, limit=limit, window_sec=window)
        if not allowed:
            try:
                from src.api.security_audit import log_unusual_traffic

                log_unusual_traffic(
                    "rate_limited",
                    ip=ip,
                    detail=f"bucket={bucket} bot={bot}",
                )
            except Exception:
                pass
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Please slow down and try again later.",
                headers={
                    "Retry-After": str(max(1, int(retry))),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )


class AbuseProtectionMiddleware(BaseHTTPMiddleware):
    """Global rate limiting + bot heuristics for all non-exempt routes."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        from src.core.config import settings

        if not bool(getattr(settings, "ABUSE_PROTECTION_ENABLED", True)):
            return await call_next(request)

        path = request.url.path
        bucket = classify_request(path, request.method)
        if bucket == "exempt":
            return await call_next(request)

        # Auth routes keep handler-level limits; still apply a coarse IP cap.
        ip = client_ip(request)
        bot = _is_bot_client(request)
        guest = bool(
            request.headers.get("x-guest-session-id")
            or request.headers.get("X-Guest-Session-Id")
        ) and not (request.headers.get("authorization") or "").lower().startswith(
            "bearer "
        )
        limit, window = _bucket_limits(bucket, bot=bot, guest=guest)
        ident = _identity_key(request)
        limiter = get_abuse_limiter()

        # IP + identity (token/guest) buckets.
        for key, lim in (
            (f"mw:{bucket}:ip:{ip}", limit),
            (f"mw:{bucket}:id:{ident}", max(3, limit // 2) if bucket != "ai" else limit),
        ):
            allowed, retry, remaining = limiter.check(
                key, limit=lim, window_sec=window
            )
            if not allowed:
                try:
                    from src.api.security_audit import log_unusual_traffic

                    log_unusual_traffic(
                        "rate_limited",
                        ip=ip,
                        detail=f"middleware bucket={bucket} bot={bot} path={path}",
                    )
                except Exception:
                    pass
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "Rate limit exceeded. Please slow down and try again later."
                    },
                    headers={
                        "Retry-After": str(max(1, int(retry))),
                        "X-RateLimit-Limit": str(lim),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Bucket": bucket,
                    },
                )

        if bot and bool(getattr(settings, "ABUSE_LOG_BOT_CLIENTS", True)):
            log.info(
                "event=bot_client ip=%s path=%s ua=%s",
                ip,
                path,
                (request.headers.get("user-agent") or "")[:80],
            )

        response = await call_next(request)
        response.headers.setdefault("X-RateLimit-Limit", str(limit))
        response.headers.setdefault("X-RateLimit-Bucket", bucket)
        return response
