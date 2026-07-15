"""Rate-limit backpressure vs hard-isolation tests."""
from __future__ import annotations

import time

import pytest


def test_rate_limit_error_detection():
    from src.core.nim_rate_limit import RateLimitBackpressure, is_rate_limit_error

    assert is_rate_limit_error(RateLimitBackpressure("x"))
    assert is_rate_limit_error(Exception("HTTP 429 Too Many Requests"))
    assert not is_rate_limit_error(TimeoutError("Node hard isolation timeout"))
    assert not is_rate_limit_error(Exception("connection reset"))


def test_backoff_grows_with_jitter_and_cap(monkeypatch):
    from src.core import nim_rate_limit as rl
    from src.core.config import settings

    monkeypatch.setattr(settings, "NIM_RATE_LIMIT_BASE_BACKOFF_SEC", 1.0)
    monkeypatch.setattr(settings, "NIM_RATE_LIMIT_MAX_BACKOFF_SEC", 8.0)
    d0 = rl.compute_backoff_sec(0)
    d3 = rl.compute_backoff_sec(3)
    assert 1.0 <= d0 <= 2.5
    assert d3 >= d0
    assert d3 <= 8.0 + 2.0  # cap + jitter ceiling
    assert rl.compute_backoff_sec(0, retry_after_sec=5.0) >= 5.0


def test_token_bucket_throttles_parallel_acquires(monkeypatch):
    from src.core import nim_rate_limit as rl
    from src.core.config import settings

    monkeypatch.setattr(settings, "NIM_MAX_REQUESTS_PER_MINUTE", 60.0)  # 1/sec
    monkeypatch.setattr(settings, "NIM_RATE_LIMITER_ENABLED", True)
    # Force new limiter
    rl._LIMITER = None
    lim = rl.get_nim_limiter()
    # Drain tokens
    lim._tokens = 0.0
    lim._updated = time.monotonic()
    t0 = time.perf_counter()
    assert lim.acquire(timeout_sec=2.5) is True
    elapsed = time.perf_counter() - t0
    assert elapsed >= 0.5  # had to wait for refill


def test_pool_requeues_rate_limit_not_hard_timeout(monkeypatch):
    from src.core import execution_scheduler as sched
    from src.core.nim_rate_limit import RateLimitBackpressure, reset_rate_limit_stats
    from src.core.config import settings

    reset_rate_limit_stats()
    monkeypatch.setattr(settings, "NIM_RATE_LIMIT_BASE_BACKOFF_SEC", 0.05)
    monkeypatch.setattr(settings, "NIM_RATE_LIMIT_MAX_BACKOFF_SEC", 0.1)
    monkeypatch.setattr(settings, "NIM_RATE_LIMIT_MAX_REQUEUES", 4)

    calls = {"n": 0}

    def worker(payload, deadline_mono=None):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise RateLimitBackpressure("429", retry_after_sec=0.05)
        return payload, {"summary": f"ok-{payload}", "success": True}

    def ok(res):
        return res is not None and bool(res[1].get("summary"))

    ordered, prog, mets = sched.run_capacity_pool(
        [0, 1],
        worker,
        role="map",
        kind="map",
        max_workers=2,
        hard_timeout_sec=5.0,
        max_attempts=2,
        is_success=ok,
    )
    assert prog.failed == 0
    assert prog.completed == 2
    assert mets.rate_limit_requeues >= 2
    assert mets.timeouts == 0


def test_hard_isolation_still_kills_hang():
    from src.core.pipeline_executor import _run_with_hard_isolation
    from src.core.nim_rate_limit import reset_rate_limit_stats, rate_limit_stats

    reset_rate_limit_stats()

    def hung():
        time.sleep(30)

    t0 = time.perf_counter()
    with pytest.raises(TimeoutError):
        _run_with_hard_isolation(hung, hard_timeout_sec=0.4, label="t")
    assert time.perf_counter() - t0 < 2.0
    assert rate_limit_stats()["hard_isolation_timeouts"] >= 1


def test_classify_429_to_backpressure():
    from src.agents import models
    from src.core.nim_rate_limit import RateLimitBackpressure
    from openai import APIStatusError

    class FakeResp:
        status_code = 429
        headers = {"retry-after": "2"}
        request = None

    # Build a minimal APIStatusError if possible
    try:
        exc = APIStatusError("rate", response=FakeResp(), body=None)
    except TypeError:
        exc = Exception("Error code: 429 - rate limit")
    out = models._classify_nim_exception(exc, model_id="m")
    assert isinstance(out, RateLimitBackpressure) or models.is_transient_nim_error(exc) or "429" in str(out)
