"""
NIM rate-limit backpressure vs genuine hang isolation.

429 / RateLimitError is fast-failing backpressure → exponential backoff + requeue.
Genuine hangs still use hard-isolation kill/reassign (separate path).
"""
from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any, Dict, Optional

from src.core.config import settings

log = logging.getLogger(__name__)


class RateLimitBackpressure(Exception):
    """
    Raised when NIM returns 429 / rate-limit — not a hung socket.

    Capacity pool must backoff-and-requeue; must NOT hard-isolate.
    """

    def __init__(
        self,
        message: str = "NIM rate limit",
        *,
        retry_after_sec: Optional[float] = None,
        status_code: int = 429,
    ):
        super().__init__(message)
        self.retry_after_sec = retry_after_sec
        self.status_code = status_code


def is_rate_limit_error(exc: Optional[BaseException]) -> bool:
    if exc is None:
        return False
    if isinstance(exc, RateLimitBackpressure):
        return True
    name = type(exc).__name__
    if name in ("RateLimitError", "RateLimitBackpressure"):
        return True
    code = getattr(exc, "status_code", None)
    try:
        if code is not None and int(code) == 429:
            return True
    except (TypeError, ValueError):
        pass
    err = str(exc).lower()
    return (
        "429" in err
        or "rate limit" in err
        or "rate_limit" in err
        or "too many requests" in err
    )


def compute_backoff_sec(attempt: int, *, retry_after_sec: Optional[float] = None) -> float:
    """Exponential backoff with jitter; honor Retry-After when present."""
    base = float(getattr(settings, "NIM_RATE_LIMIT_BASE_BACKOFF_SEC", 1.0) or 1.0)
    cap = float(getattr(settings, "NIM_RATE_LIMIT_MAX_BACKOFF_SEC", 60.0) or 60.0)
    if retry_after_sec is not None and retry_after_sec > 0:
        delay = min(cap, float(retry_after_sec))
    else:
        delay = min(cap, base * (2 ** max(0, int(attempt))))
    jitter = random.uniform(0.0, min(1.0, delay * 0.25))
    return max(0.05, delay + jitter)


# --- Global token-bucket (shared across all workers / stages) ---------------

class _TokenBucket:
    def __init__(self, rate_per_min: float):
        self._rate_per_sec = max(0.01, float(rate_per_min) / 60.0)
        self._tokens = float(rate_per_min)  # start full for one minute budget
        self._max = float(rate_per_min)
        self._updated = time.monotonic()
        self._cv = threading.Condition()
        self._acquired = 0
        self._wait_ms_sum = 0.0

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._updated
        self._updated = now
        self._tokens = min(self._max, self._tokens + elapsed * self._rate_per_sec)

    def acquire(self, *, timeout_sec: Optional[float] = None) -> bool:
        """Block until a token is available. Returns False on timeout."""
        deadline = (
            None
            if timeout_sec is None
            else time.monotonic() + max(0.0, float(timeout_sec))
        )
        t0 = time.perf_counter()
        with self._cv:
            while True:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    self._acquired += 1
                    self._wait_ms_sum += (time.perf_counter() - t0) * 1000.0
                    return True
                # Wait for next token
                need = (1.0 - self._tokens) / self._rate_per_sec
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return False
                    need = min(need, remaining)
                self._cv.wait(timeout=max(0.01, need))

    def snapshot(self) -> Dict[str, Any]:
        with self._cv:
            self._refill()
            return {
                "rate_per_min": round(self._rate_per_sec * 60.0, 2),
                "tokens": round(self._tokens, 2),
                "acquired": self._acquired,
                "avg_wait_ms": round(
                    self._wait_ms_sum / self._acquired if self._acquired else 0.0, 1
                ),
            }


_LIMITER_LOCK = threading.Lock()
_LIMITER: Optional[_TokenBucket] = None

# Process-wide counters for validation reports
_STATS_LOCK = threading.Lock()
_STATS: Dict[str, Any] = {
    "rate_limit_signals": 0,
    "rate_limit_requeues": 0,
    "rate_limit_backoff_sec_sum": 0.0,
    "hard_isolation_timeouts": 0,
}


def reset_rate_limit_stats() -> None:
    with _STATS_LOCK:
        for k in list(_STATS.keys()):
            _STATS[k] = 0 if not k.endswith("_sum") else 0.0


def record_rate_limit_signal() -> None:
    with _STATS_LOCK:
        _STATS["rate_limit_signals"] = int(_STATS["rate_limit_signals"]) + 1


def record_rate_limit_requeue(backoff_sec: float) -> None:
    with _STATS_LOCK:
        _STATS["rate_limit_requeues"] = int(_STATS["rate_limit_requeues"]) + 1
        _STATS["rate_limit_backoff_sec_sum"] = (
            float(_STATS["rate_limit_backoff_sec_sum"]) + float(backoff_sec)
        )


def record_hard_isolation_timeout() -> None:
    with _STATS_LOCK:
        _STATS["hard_isolation_timeouts"] = int(_STATS["hard_isolation_timeouts"]) + 1


def rate_limit_stats() -> Dict[str, Any]:
    with _STATS_LOCK:
        requeues = int(_STATS["rate_limit_requeues"])
        backoff_sum = float(_STATS["rate_limit_backoff_sec_sum"])
        return {
            "rate_limit_signals": int(_STATS["rate_limit_signals"]),
            "rate_limit_requeues": requeues,
            "avg_backoff_sec": round(backoff_sum / requeues, 2) if requeues else 0.0,
            "hard_isolation_timeouts": int(_STATS["hard_isolation_timeouts"]),
            "limiter": get_nim_limiter().snapshot(),
        }


def get_nim_limiter() -> _TokenBucket:
    global _LIMITER
    with _LIMITER_LOCK:
        rate = float(getattr(settings, "NIM_MAX_REQUESTS_PER_MINUTE", 30.0) or 30.0)
        if _LIMITER is None or abs(_LIMITER._rate_per_sec * 60.0 - rate) > 0.01:
            _LIMITER = _TokenBucket(rate)
        return _LIMITER


def acquire_nim_request_slot(*, timeout_sec: Optional[float] = None) -> None:
    """
    Acquire one global NIM request token. Workers queue on the limiter,
    not on each other — parallelism is preserved within the allowed rate.
    """
    enabled = bool(getattr(settings, "NIM_RATE_LIMITER_ENABLED", True))
    if not enabled:
        return
    lim = get_nim_limiter()
    ok = lim.acquire(timeout_sec=timeout_sec)
    if not ok:
        raise RateLimitBackpressure(
            "Timed out waiting for NIM global rate-limiter token",
            retry_after_sec=compute_backoff_sec(0),
        )
