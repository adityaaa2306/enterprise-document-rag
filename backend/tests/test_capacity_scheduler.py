"""Capacity-aware endpoint manager + pull-based execution scheduler."""
from __future__ import annotations

import threading
import time
from typing import Any, List, Tuple

import pytest


def test_endpoint_respects_max_concurrent(monkeypatch):
    from src.agents import nim_endpoint_pool as pool
    from src.core.config import settings

    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "k1")
    monkeypatch.setattr(settings, "NIM_ENDPOINT_2_API_KEY", "")
    monkeypatch.setattr(settings, "NIM_ENDPOINT_3_API_KEY", "")
    monkeypatch.setattr(settings, "NIM_API_KEYS", "")
    monkeypatch.setattr(settings, "NIM_ENDPOINT_MAX_CONCURRENT", 2)
    monkeypatch.setattr(settings, "NIM_ENDPOINT_STRATEGY", "least_load")
    pool.load_endpoint_pool()

    a = pool.acquire_endpoint(role="map", block=False)
    b = pool.acquire_endpoint(role="map", block=False)
    c = pool.acquire_endpoint(role="map", block=False)
    assert a is not None and b is not None
    assert c is None  # at capacity
    pool.release_endpoint(a, ok=True, latency_ms=10)
    d = pool.acquire_endpoint(role="map", block=False)
    assert d is not None
    pool.release_endpoint(b, ok=True, latency_ms=10)
    pool.release_endpoint(d, ok=True, latency_ms=10)


def test_least_load_prefers_lowest_active(monkeypatch):
    from src.agents import nim_endpoint_pool as pool
    from src.core.config import settings

    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "k1")
    monkeypatch.setattr(settings, "NIM_ENDPOINT_2_API_KEY", "k2")
    monkeypatch.setattr(settings, "NIM_ENDPOINT_3_API_KEY", "k3")
    monkeypatch.setattr(settings, "NIM_API_KEYS", "")
    monkeypatch.setattr(settings, "NIM_ENDPOINT_MAX_CONCURRENT", 3)
    monkeypatch.setattr(settings, "NIM_ENDPOINT_STRATEGY", "least_load")
    pool.load_endpoint_pool()

    leases = [pool.acquire_endpoint(role="map", block=False) for _ in range(3)]
    ids = {L.endpoint_id for L in leases if L}
    assert len(ids) == 3
    for L in leases:
        pool.release_endpoint(L, ok=True, latency_ms=50)


def test_effective_workers_capped_by_capacity(monkeypatch):
    from src.core.config import settings

    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "k1")
    monkeypatch.setattr(settings, "NIM_ENDPOINT_2_API_KEY", "k2")
    monkeypatch.setattr(settings, "NIM_ENDPOINT_3_API_KEY", "k3")
    monkeypatch.setattr(settings, "NIM_API_KEYS", "")
    monkeypatch.setattr(settings, "NIM_ENDPOINT_MAX_CONCURRENT", 3)
    monkeypatch.setattr(settings, "MAP_MAX_WORKERS", 24)
    monkeypatch.setattr(settings, "COMPILE_MAX_WORKERS", 20)
    monkeypatch.setattr(settings, "RUN_EMBEDDED_WORKER", False)
    assert settings.nim_endpoint_count() == 3
    # 3 endpoints × 3 concurrent = 9
    assert settings.effective_map_max_workers() == 9
    assert settings.effective_compile_max_workers() <= 9


def test_pull_scheduler_never_exceeds_capacity(monkeypatch):
    from src.core import execution_scheduler as sched

    active = 0
    peak = 0
    lock = threading.Lock()
    capacity = 3

    def work(payload: Tuple[int, str]) -> Tuple[int, str]:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        idx, _ = payload
        return idx, f"ok-{idx}"

    # Patch capacity probe
    monkeypatch.setattr(sched, "_endpoint_capacity", lambda role="map": capacity)

    items = [(i, f"c{i}") for i in range(12)]
    ordered, progress, metrics = sched.run_capacity_pool(
        items,
        work,
        role="map",
        kind="map",
        max_workers=16,
        hard_timeout_sec=5.0,
        max_attempts=1,
        is_success=lambda r: r is not None and str(r[1]).startswith("ok"),
    )
    assert peak <= capacity
    assert progress.completed == 12
    assert progress.failed == 0
    assert sum(1 for r in ordered if r is not None) == 12


def test_pull_scheduler_retries_empty(monkeypatch):
    from src.core import execution_scheduler as sched

    monkeypatch.setattr(sched, "_endpoint_capacity", lambda role="map": 2)
    attempts = {}

    def work(payload):
        idx = payload[0]
        attempts[idx] = attempts.get(idx, 0) + 1
        if attempts[idx] < 2:
            return idx, ""  # empty → retry
        return idx, "summary"

    items = [(0, "a"), (1, "b")]
    ordered, progress, _mets = sched.run_capacity_pool(
        items,
        work,
        role="map",
        max_workers=2,
        hard_timeout_sec=5.0,
        max_attempts=3,
        is_success=lambda r: bool(r and (r[1] or "").strip()),
    )
    assert progress.completed == 2
    assert attempts[0] == 2 and attempts[1] == 2
    assert ordered[0][1] == "summary"


def test_hard_timeout_does_not_wait_390s(monkeypatch):
    from src.core import execution_scheduler as sched

    monkeypatch.setattr(sched, "_endpoint_capacity", lambda role="map": 1)

    def hang(_payload):
        time.sleep(30)
        return 0, "late"

    t0 = time.perf_counter()
    _ordered, progress, mets = sched.run_capacity_pool(
        [(0, "x")],
        hang,
        role="map",
        max_workers=1,
        hard_timeout_sec=0.4,
        max_attempts=1,
        is_success=lambda r: bool(r and (r[1] or "").strip()),
    )
    elapsed = time.perf_counter() - t0
    assert elapsed < 5.0
    assert progress.failed == 1
    assert mets.timeouts >= 1
