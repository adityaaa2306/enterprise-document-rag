"""
Structured security audit logging.

Emits machine-parseable lines on logger ``security.audit`` for:
- authentication attempts (success / failure)
- API errors (5xx / unexpected)
- unusual traffic patterns (auth abuse, error bursts)

Never log passwords, tokens, or full Authorization headers.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, Optional

log = logging.getLogger("security.audit")

_lock = threading.Lock()
_ip_events: Dict[str, Deque[float]] = defaultdict(deque)
_ip_auth_failures: Dict[str, Deque[float]] = defaultdict(deque)


def _client_ip(request: Any) -> str:
    try:
        from src.api.auth_rate_limit import client_ip

        return client_ip(request)
    except Exception:
        try:
            if request.client and request.client.host:
                return str(request.client.host)
        except Exception:
            pass
    return "unknown"


def log_auth_event(
    event: str,
    *,
    request: Any = None,
    email: Optional[str] = None,
    success: bool = False,
    detail: Optional[str] = None,
    user_id: Optional[int] = None,
) -> None:
    """Log an authentication lifecycle event."""
    ip = _client_ip(request) if request is not None else "n/a"
    request_id = None
    try:
        if request is not None:
            request_id = request.headers.get("x-request-id")
    except Exception:
        pass
    # Never log raw emails in full in high-sensitivity mode — keep domain + hash suffix.
    email_safe = _redact_email(email)
    log.info(
        "event=%s success=%s ip=%s email=%s user_id=%s request_id=%s detail=%s",
        event,
        success,
        ip,
        email_safe,
        user_id if user_id is not None else "-",
        request_id or "-",
        (detail or "-")[:160],
    )
    if not success and event.startswith("login"):
        _note_auth_failure(ip)


def log_api_error(
    *,
    request: Any = None,
    status_code: int,
    detail: Optional[str] = None,
    exc_type: Optional[str] = None,
) -> None:
    ip = _client_ip(request) if request is not None else "n/a"
    path = "-"
    method = "-"
    request_id = "-"
    try:
        if request is not None:
            path = request.url.path
            method = request.method
            request_id = request.headers.get("x-request-id") or "-"
    except Exception:
        pass
    level = logging.ERROR if status_code >= 500 else logging.WARNING
    log.log(
        level,
        "event=api_error status=%s method=%s path=%s ip=%s request_id=%s "
        "exc_type=%s detail=%s",
        status_code,
        method,
        path,
        ip,
        request_id,
        exc_type or "-",
        (detail or "-")[:200],
    )
    if status_code >= 400:
        _note_error_burst(ip, status_code)


def log_unusual_traffic(
    reason: str,
    *,
    ip: str,
    detail: Optional[str] = None,
    count: Optional[int] = None,
) -> None:
    log.warning(
        "event=unusual_traffic reason=%s ip=%s count=%s detail=%s",
        reason,
        ip,
        count if count is not None else "-",
        (detail or "-")[:200],
    )


def _redact_email(email: Optional[str]) -> str:
    if not email:
        return "-"
    e = str(email).strip().lower()
    if "@" not in e:
        return "***"
    local, _, domain = e.partition("@")
    if len(local) <= 2:
        masked = "*" * len(local)
    else:
        masked = local[0] + "***" + local[-1]
    return f"{masked}@{domain}"


def _note_auth_failure(ip: str) -> None:
    now = time.monotonic()
    with _lock:
        q = _ip_auth_failures[ip]
        q.append(now)
        while q and now - q[0] > 300.0:
            q.popleft()
        n = len(q)
    if n >= 8:
        log_unusual_traffic(
            "auth_failure_burst",
            ip=ip,
            count=n,
            detail=">=8 failed auth attempts in 5m",
        )


def _note_error_burst(ip: str, status_code: int) -> None:
    now = time.monotonic()
    with _lock:
        q = _ip_events[ip]
        q.append(now)
        while q and now - q[0] > 60.0:
            q.popleft()
        n = len(q)
    if n >= 40:
        log_unusual_traffic(
            "error_burst",
            ip=ip,
            count=n,
            detail=f">=40 client/server errors in 60s (last_status={status_code})",
        )


def reset_security_audit_state() -> None:
    """Test helper."""
    with _lock:
        _ip_events.clear()
        _ip_auth_failures.clear()
