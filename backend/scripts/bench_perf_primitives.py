"""
Offline micro-benchmark for perf primitives (no NIM required).

Usage:
  cd backend && python -m scripts.bench_perf_primitives
"""
from __future__ import annotations

import time

from src.agents.quality_validation import validate_chunks
from src.monitoring.ingestion_latency import format_latency_table
from src.perf.profiler import format_waterfall, rank_bottlenecks


class _C:
    def __init__(self, content: str):
        self.content = content


def _make_doc(n: int):
    chunks = []
    summaries = []
    for i in range(n):
        body = (
            f"Section {i}: The adaptive carbon-aware pipeline routes chunk {i} "
            f"through light medium or heavy tiers based on complexity signals. "
        ) * 8
        chunks.append(_C(body))
        summaries.append(
            f"Section {i} covers adaptive routing for chunk complexity and carbon budgets."
        )
    return chunks, summaries


def main():
    sizes = [8, 32, 64]
    print("=== QVA validate_chunks wall time (parallel workers) ===")
    for n in sizes:
        chunks, summaries = _make_doc(n)
        t0 = time.perf_counter()
        v = validate_chunks(chunks, summaries)
        ms = (time.perf_counter() - t0) * 1000
        print(
            f"n={n:3d}  {ms:8.1f} ms  passed={v.passed}  "
            f"fail_ratio={v.details.get('fail_ratio')}"
        )

    # Synthetic waterfall (illustrative before/after shape)
    before = {
        "triage_ms": 8000,
        "feature_extract_ms": 12000,
        "plan_pipeline_ms": 200,
        "cre_and_route_ms": 300,
        "map_summarize_ms": 180000,
        "validate_map_ms": 4000,
        "escalate_ms": 45000,
        "reduce_compile_ms": 60000,
        "store_embed_ms": 25000,
        "finalize_metrics_ms": 3000,
        "total_ms": 337500,
    }
    after = {
        "triage_ms": 5000,
        "feature_extract_ms": 8000,
        "plan_pipeline_ms": 200,
        "cre_and_route_ms": 300,
        "map_summarize_ms": 55000,  # higher MAP_MAX_WORKERS
        "validate_map_ms": 800,  # parallel + no dup escalate validate
        "escalate_ms": 20000,
        "reduce_compile_ms": 28000,  # parallel hierarchical batches
        "store_embed_ms": 4000,  # prefetch overlap + bulk upsert
        "finalize_metrics_ms": 500,  # grid cache
        "total_ms": 121800,
    }
    print("\n=== BEFORE (typical large-doc profile) ===")
    print(format_waterfall(before))
    print("Bottlenecks:", rank_bottlenecks(before)[:5])
    print("\n=== AFTER (optimized concurrency + cache) ===")
    print(format_waterfall(after))
    print("Bottlenecks:", rank_bottlenecks(after)[:5])
    speedup = before["total_ms"] / after["total_ms"]
    print(f"\nIllustrative wall-clock speedup: {speedup:.2f}x")
    print(
        "\nNote: real NIM-bound map/compile times depend on model latency; "
        "run a live job and inspect local_db/aux/ingest_latency/<job_id>.json"
    )


if __name__ == "__main__":
    main()
