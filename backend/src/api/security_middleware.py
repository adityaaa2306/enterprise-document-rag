"""
HTTPS enforcement and security response headers for production deployments.

Behind Render/Vercel reverse proxies we trust ``X-Forwarded-Proto`` when
``TRUST_PROXY_HEADERS`` is enabled (default in production).
"""
from __future__ import annotations

import logging
from typing import Callable, Optional
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from src.core.config import settings

log = logging.getLogger("security.middleware")


def _forwarded_proto(request: Request) -> Optional[str]:
    proto = request.headers.get("x-forwarded-proto") or request.headers.get(
        "X-Forwarded-Proto"
    )
    if proto:
        return proto.split(",")[0].strip().lower()
    return None


def _is_https(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    if bool(getattr(settings, "TRUST_PROXY_HEADERS", True)):
        return _forwarded_proto(request) == "https"
    return False


def https_enforced() -> bool:
    flag = getattr(settings, "FORCE_HTTPS", None)
    if flag is None:
        return bool(settings.is_production)
    return bool(flag)


class HttpsRedirectMiddleware(BaseHTTPMiddleware):
    """Redirect plain HTTP → HTTPS when FORCE_HTTPS / production."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if https_enforced() and not _is_https(request):
            # Allow local health probes on loopback without redirect loops.
            host = (request.client.host if request.client else "") or ""
            if host in ("127.0.0.1", "::1", "localhost") and request.url.path in (
                "/api/health",
                "/api/ready",
            ):
                return await call_next(request)
            url = request.url.replace(scheme="https")
            log.info(
                "event=https_redirect path=%s host=%s",
                request.url.path,
                request.url.hostname,
            )
            return RedirectResponse(str(url), status_code=308)
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach standard hardening headers to every response."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=()",
        )
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        # API responses are JSON; keep CSP restrictive for accidental HTML.
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
        )
        if https_enforced() or _is_https(request):
            max_age = int(getattr(settings, "HSTS_MAX_AGE_SEC", 31536000) or 31536000)
            response.headers.setdefault(
                "Strict-Transport-Security",
                f"max-age={max_age}; includeSubDomains",
            )
        return response


def validate_database_url_for_public_exposure(database_url: str) -> None:
    """
    Raise RuntimeError if DATABASE_URL looks publicly reachable without TLS.

    Managed providers (Neon, etc.) should use SSL. Direct public IPs without
    sslmode=require are rejected in production.
    """
    raw = (database_url or "").strip()
    if not raw:
        return
    low = raw.lower()
    if "sslmode=disable" in low or "ssl=false" in low:
        raise RuntimeError(
            "DATABASE_URL must not disable SSL in production "
            "(remove sslmode=disable). Use sslmode=require."
        )

    # Parse host after scheme://
    try:
        # sqlalchemy URLs: postgresql+psycopg://user:pass@host:port/db
        normalized = raw.replace("postgresql+psycopg://", "postgresql://", 1)
        normalized = normalized.replace("postgres+psycopg://", "postgresql://", 1)
        parsed = urlparse(normalized)
        host = (parsed.hostname or "").lower()
    except Exception:
        host = ""

    has_ssl = (
        "sslmode=require" in low
        or "sslmode=verify-full" in low
        or "sslmode=verify-ca" in low
        or "ssl=true" in low
    )
    managed = any(
        h in host
        for h in (
            "neon.tech",
            "amazonaws.com",
            "azure.com",
            "googleapis.com",
            "supabase.co",
            "render.com",
            "elephant.sql",
        )
    )
    # Private / compose network hosts are fine without public exposure.
    private = (
        host in ("localhost", "127.0.0.1", "postgres", "db")
        or host.startswith("10.")
        or host.startswith("192.168.")
        or host.endswith(".local")
        or host.endswith(".internal")
    )

    if private:
        log.info(
            "DATABASE_URL host=%s appears private/compose — ensure it is not "
            "published on 0.0.0.0 to the public internet",
            host or "?",
        )
        return

    if managed and not has_ssl:
        log.warning(
            "DATABASE_URL for managed host %s has no explicit sslmode=require — "
            "Neon/AWS usually enforce TLS; add ?sslmode=require to be explicit",
            host,
        )
        return

    if not has_ssl:
        raise RuntimeError(
            f"DATABASE_URL host {host or '(unknown)'} must use TLS in production "
            "(append ?sslmode=require). Do not expose Postgres on the public "
            "internet without SSL and IP allowlisting."
        )
