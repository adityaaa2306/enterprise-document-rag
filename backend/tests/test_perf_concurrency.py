"""Perf concurrency + capacity helpers (no NIM calls)."""
from __future__ import annotations

from src.core.config import Settings


def test_effective_nim_capacity_sums_per_endpoint():
    s = Settings(
        NVIDIA_API_KEY="k1",
        NIM_ENDPOINT_2_API_KEY="k2",
        NIM_ENDPOINT_3_API_KEY="k3",
        NIM_ENDPOINT_MAX_CONCURRENT=3,
        NIM_ENDPOINT_1_MAX_CONCURRENT=6,
        NIM_ENDPOINT_2_MAX_CONCURRENT=6,
        NIM_ENDPOINT_3_MAX_CONCURRENT=6,
        NIM_ENDPOINT_POOL_ENABLED=True,
        RUN_EMBEDDED_WORKER=True,
        EMBEDDED_MAP_MAX_WORKERS=12,
        MAX_PARALLEL_WORKERS=12,
        MAP_MAX_WORKERS=12,
    )
    assert s.nim_endpoint_count() == 3
    assert s.effective_nim_capacity() == 18
    assert s.effective_parallel_workers() == 12


def test_embedded_cap_still_bounds_workers():
    s = Settings(
        NVIDIA_API_KEY="k1",
        NIM_ENDPOINT_2_API_KEY="k2",
        NIM_ENDPOINT_3_API_KEY="",
        NIM_API_KEYS="",
        NIM_ENDPOINT_MAX_CONCURRENT=6,
        NIM_ENDPOINT_1_MAX_CONCURRENT=6,
        NIM_ENDPOINT_2_MAX_CONCURRENT=6,
        NIM_ENDPOINT_POOL_ENABLED=True,
        RUN_EMBEDDED_WORKER=True,
        EMBEDDED_MAP_MAX_WORKERS=4,
        MAX_PARALLEL_WORKERS=12,
    )
    assert s.effective_nim_capacity() == 12
    assert s.effective_parallel_workers() == 4


def test_compile_workers_honor_compile_max():
    s = Settings(
        NVIDIA_API_KEY="k1",
        NIM_ENDPOINT_2_API_KEY="k2",
        NIM_ENDPOINT_3_API_KEY="k3",
        NIM_ENDPOINT_1_MAX_CONCURRENT=6,
        NIM_ENDPOINT_2_MAX_CONCURRENT=6,
        NIM_ENDPOINT_3_MAX_CONCURRENT=6,
        NIM_ENDPOINT_POOL_ENABLED=True,
        RUN_EMBEDDED_WORKER=True,
        EMBEDDED_MAP_MAX_WORKERS=12,
        COMPILE_MAX_WORKERS=6,
        MAX_PARALLEL_WORKERS=12,
    )
    assert s.effective_compile_max_workers() == 6


def test_waterfall_formatter():
    from src.perf.profiler import format_waterfall, rank_bottlenecks

    stages = {"map_ms": 120000, "validate_ms": 800, "compile_ms": 40000, "total_ms": 165000}
    text = format_waterfall(stages)
    assert "map_ms" in text
    ranked = rank_bottlenecks(stages)
    assert ranked[0]["stage"] == "map_ms" or ranked[0].get("name") == "map_ms" or "map" in str(ranked[0])
