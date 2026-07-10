"""
Lightweight request logging for production operational validation (Phase 5).

Logs: method, path, status, duration_ms. Does not change business logic.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = logging.getLogger("http.access")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000.0
            log.exception(
                "request_id=%s method=%s path=%s status=500 duration_ms=%.1f",
                request_id,
                request.method,
                request.url.path,
                duration_ms,
            )
            raise

        duration_ms = (time.perf_counter() - start) * 1000.0
        response.headers["X-Request-Id"] = request_id
        path = request.url.path
        level = logging.DEBUG if path in ("/api/health", "/api/ready") and response.status_code < 400 else logging.INFO
        log.log(
            level,
            "request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
            request_id,
            request.method,
            path,
            response.status_code,
            duration_ms,
        )
        return response
