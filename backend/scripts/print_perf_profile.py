"""
Offline performance report + synthetic waterfall from latest job latency JSON.

Does not call NIM. Prints Phase 1–2 style profile from artifacts when present.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.config import settings
from src.perf.profiler import format_waterfall, rank_bottlenecks


def print_capacity_report() -> None:
    print("=== Concurrency / capacity (current settings) ===")
    print(f"nim_endpoint_count     = {settings.nim_endpoint_count()}")
    print(f"effective_nim_capacity = {settings.effective_nim_capacity()}")
    print(f"effective_parallel     = {settings.effective_parallel_workers()}")
    print(f"effective_compile      = {settings.effective_compile_max_workers()}")
    print(f"RUN_EMBEDDED_WORKER    = {settings.RUN_EMBEDDED_WORKER}")
    print(f"EMBEDDED_MAP_MAX       = {settings.EMBEDDED_MAP_MAX_WORKERS}")
    print(f"NIM_ENDPOINT_MAX_CONC  = {settings.NIM_ENDPOINT_MAX_CONCURRENT}")
    print(f"NIM_MAX_RPM            = {settings.NIM_MAX_REQUESTS_PER_MINUTE}")
    print()


def load_latest_latency() -> dict | None:
    art = ROOT / "artifacts" / "ingestion_latency"
    if not art.exists():
        return None
    files = sorted(art.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return None
    return json.loads(files[0].read_text(encoding="utf-8"))


def main() -> int:
    print_capacity_report()
    data = load_latest_latency()
    if not data:
        print("No ingestion_latency artifacts yet — run a job to produce before/after waterfalls.")
        print()
        print("Expected bottleneck ranking (from prior profile):")
        demo = {
            "map_summarize_ms": 180000,
            "compile_ms": 60000,
            "feature_extract_ms": 15000,
            "triage_ms": 8000,
            "validate_ms": 500,
            "store_ms": 4000,
            "finalize_ms": 2000,
            "total_ms": 270000,
        }
        print(format_waterfall(demo))
        print()
        for row in rank_bottlenecks(demo):
            print(f"  #{row['rank']} {row['stage']}: {row['sec']}s ({row['pct_of_stages']}%)")
        return 0

    stages = {}
    for k, v in (data.get("stages") or data).items():
        if isinstance(v, (int, float)) and k.endswith("_ms"):
            stages[k] = float(v)
    if "total_ms" not in stages and data.get("total_ms") is not None:
        stages["total_ms"] = float(data["total_ms"])
    print("=== Latest job waterfall ===")
    print(format_waterfall(stages))
    print()
    print("=== Ranked bottlenecks ===")
    for row in rank_bottlenecks(stages):
        print(f"  #{row['rank']} {row['stage']}: {row['sec']}s ({row['pct_of_stages']}%)")
    meta = data.get("meta") or {}
    if meta:
        print()
        print("=== Meta (workers / DAG timings) ===")
        for k in sorted(meta):
            if "worker" in k or "dag_" in k or "map_" in k or "embed" in k:
                print(f"  {k}={meta[k]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
