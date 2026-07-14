"""
Ingestion-path wall-clock timing (diagnostic only).

Tracks LangGraph node stages + per-chunk map-summarize NIM calls.
Does not change routing / model selection.
"""
from __future__ import annotations

import logging
import statistics
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

log = logging.getLogger(__name__)

STAGE_TRIAGE = "triage_ms"
STAGE_FEATURE_EXTRACT = "feature_extract_ms"
STAGE_PLAN_PIPELINE = "plan_pipeline_ms"
STAGE_CRE_ROUTE = "cre_and_route_ms"
STAGE_MAP_SUMMARIZE = "map_summarize_ms"
STAGE_VALIDATE = "validate_map_ms"
STAGE_ESCALATE = "escalate_ms"
STAGE_COMPILE = "reduce_compile_ms"
STAGE_STORE = "store_embed_ms"
STAGE_FINALIZE = "finalize_metrics_ms"
STAGE_TOTAL = "total_ms"

STAGE_ORDER = [
    STAGE_TRIAGE,
    STAGE_FEATURE_EXTRACT,
    STAGE_PLAN_PIPELINE,
    STAGE_CRE_ROUTE,
    STAGE_MAP_SUMMARIZE,
    STAGE_VALIDATE,
    STAGE_ESCALATE,
    STAGE_COMPILE,
    STAGE_STORE,
    STAGE_FINALIZE,
    STAGE_TOTAL,
]


def _pct(xs: List[float], p: float) -> float:
    if not xs:
        return float("nan")
    ys = sorted(xs)
    if len(ys) == 1:
        return ys[0]
    k = (len(ys) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(ys) - 1)
    if f == c:
        return ys[f]
    return ys[f] + (ys[c] - ys[f]) * (k - f)


def summarize_durations_ms(values: List[float]) -> Dict[str, Any]:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "mean": round(statistics.mean(values), 1),
        "p50": round(_pct(values, 50), 1),
        "p95": round(_pct(values, 95), 1),
        "max": round(max(values), 1),
        "min": round(min(values), 1),
    }


class IngestionLatencyTracker:
    """Accumulate stage + per-chunk timings for one summarize job."""

    def __init__(self, job_id: str = "") -> None:
        self.job_id = job_id
        self.stages: Dict[str, float] = {}
        self.stage_detail: Dict[str, Dict[str, Any]] = {}
        self.meta: Dict[str, Any] = {}
        self.chunk_calls: List[Dict[str, Any]] = []
        self.pool_samples: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._t0 = time.perf_counter()
        self._cpu0 = time.process_time()
        self._active_workers = 0
        self._peak_active = 0
        self._model_calls = 0

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        cpu0 = time.process_time()
        detail: Dict[str, Any] = {
            "start_offset_ms": round((start - self._t0) * 1000.0, 3),
        }
        try:
            from src.perf.profiler import sample_resources

            detail["resources_start"] = sample_resources()
        except Exception:
            pass
        try:
            yield
        finally:
            end = time.perf_counter()
            wall_ms = round((end - start) * 1000.0, 3)
            cpu_ms = round((time.process_time() - cpu0) * 1000.0, 3)
            self.stages[name] = wall_ms
            detail["end_offset_ms"] = round((end - self._t0) * 1000.0, 3)
            detail["wall_ms"] = wall_ms
            detail["cpu_ms"] = cpu_ms
            detail["io_wait_proxy_ms"] = round(max(0.0, wall_ms - cpu_ms), 3)
            try:
                from src.perf.profiler import sample_resources

                detail["resources_end"] = sample_resources()
            except Exception:
                pass
            self.stage_detail[name] = detail

    def set_stage(self, name: str, duration_ms: float) -> None:
        self.stages[name] = round(float(duration_ms), 3)

    def add_meta(self, **kwargs: Any) -> None:
        self.meta.update(kwargs)

    def worker_enter(self) -> int:
        with self._lock:
            self._active_workers += 1
            self._peak_active = max(self._peak_active, self._active_workers)
            active = self._active_workers
        sample = {
            "ts_ms": round((time.perf_counter() - self._t0) * 1000.0, 1),
            "active_workers": active,
            "event": "enter",
        }
        with self._lock:
            self.pool_samples.append(sample)
        return active

    def worker_exit(self) -> int:
        with self._lock:
            self._active_workers = max(0, self._active_workers - 1)
            active = self._active_workers
        sample = {
            "ts_ms": round((time.perf_counter() - self._t0) * 1000.0, 1),
            "active_workers": active,
            "event": "exit",
        }
        with self._lock:
            self.pool_samples.append(sample)
        return active

    def record_model_call(self) -> None:
        with self._lock:
            self._model_calls += 1

    def record_chunk_call(self, record: Dict[str, Any]) -> None:
        with self._lock:
            self.chunk_calls.append(record)
            self._model_calls += 1
        log.info(
            "ingest_chunk_call job_id=%s chunk=%s tier=%s model=%s "
            "queue_ms=%.1f call_ms=%.1f ok=%s retries=%s http_status=%s attempts=%s",
            self.job_id,
            record.get("chunk_index"),
            record.get("tier"),
            record.get("model_id"),
            float(record.get("queue_ms") or 0.0),
            float(record.get("call_ms") or 0.0),
            record.get("success"),
            record.get("retry_count"),
            record.get("http_status"),
            record.get("attempt_count"),
        )

    def finish(self) -> Dict[str, Any]:
        if STAGE_TOTAL not in self.stages:
            self.stages[STAGE_TOTAL] = round(
                (time.perf_counter() - self._t0) * 1000.0, 3
            )
        self.meta["pool_peak_active"] = self._peak_active
        self.meta["model_calls"] = self._model_calls
        self.meta["cpu_total_ms"] = round(
            (time.process_time() - self._cpu0) * 1000.0, 3
        )
        try:
            from src.perf.profiler import format_waterfall, rank_bottlenecks

            self.meta["waterfall"] = format_waterfall(self.stages)
            self.meta["bottleneck_rank"] = rank_bottlenecks(self.stages)
        except Exception:
            pass
        return self.as_dict()

    def as_dict(self) -> Dict[str, Any]:
        call_ms = [
            float(c["call_ms"])
            for c in self.chunk_calls
            if c.get("call_ms") is not None
        ]
        queue_ms = [
            float(c["queue_ms"])
            for c in self.chunk_calls
            if c.get("queue_ms") is not None
        ]
        failures = [c for c in self.chunk_calls if not c.get("success")]
        return {
            "stages_ms": dict(self.stages),
            "stage_detail": dict(self.stage_detail),
            "meta": dict(self.meta),
            "map_chunk_stats": {
                "call_ms": summarize_durations_ms(call_ms),
                "queue_ms": summarize_durations_ms(queue_ms),
                "failures": len(failures),
                "chunk_calls": len(self.chunk_calls),
                "avg_latency_ms": (
                    round(statistics.mean(call_ms), 1) if call_ms else None
                ),
                "model_calls": self._model_calls,
            },
            "chunk_calls": list(self.chunk_calls),
            "pool_samples": list(self.pool_samples[-200:]),  # cap payload size
            "pool_peak_active": self._peak_active,
            # Wall-clock origin for reconstructing tracker across LangGraph nodes
            "_t0_wall": time.time() - (time.perf_counter() - self._t0),
            "_elapsed_so_far_ms": round((time.perf_counter() - self._t0) * 1000.0, 3),
            "_model_calls": self._model_calls,
            "_cpu0": self._cpu0,
        }


def log_ingestion_latency(job_id: str, latency: Dict[str, Any]) -> None:
    stages = latency.get("stages_ms") or {}
    ordered = {k: stages[k] for k in STAGE_ORDER if k in stages}
    extras = {k: v for k, v in stages.items() if k not in ordered}
    ordered.update(extras)
    stats = latency.get("map_chunk_stats") or {}
    log.info(
        "ingest_latency job_id=%s stages_ms=%s map_chunk_stats=%s meta=%s peak_pool=%s",
        job_id,
        ordered,
        stats,
        latency.get("meta") or {},
        latency.get("pool_peak_active"),
    )


def format_latency_table(latency: Dict[str, Any]) -> str:
    """Human-readable table matching bench_rag_latency style."""
    lines: List[str] = []
    stages = latency.get("stages_ms") or {}
    lines.append("=== Ingestion stage breakdown (ms) ===")
    header = f"{'stage':28} {'ms':>12} {'sec':>10}"
    lines.append(header)
    lines.append("-" * len(header))
    for stage in STAGE_ORDER:
        if stage not in stages:
            continue
        ms = float(stages[stage])
        lines.append(f"{stage:28} {ms:12.1f} {ms / 1000.0:10.1f}")
    extras = [k for k in stages if k not in STAGE_ORDER]
    for stage in extras:
        ms = float(stages[stage])
        lines.append(f"{stage:28} {ms:12.1f} {ms / 1000.0:10.1f}")

    stats = (latency.get("map_chunk_stats") or {}).get("call_ms") or {}
    if stats.get("n"):
        lines.append("")
        lines.append("=== Map-summarize per-chunk call_ms ===")
        lines.append(
            f"n={stats['n']} mean={stats['mean']} p50={stats['p50']} "
            f"p95={stats['p95']} max={stats['max']} min={stats['min']}"
        )
    qstats = (latency.get("map_chunk_stats") or {}).get("queue_ms") or {}
    if qstats.get("n"):
        lines.append(
            f"queue_ms n={qstats['n']} mean={qstats['mean']} p50={qstats['p50']} "
            f"p95={qstats['p95']} max={qstats['max']}"
        )
    meta = latency.get("meta") or {}
    if meta:
        lines.append("")
        lines.append(f"routing: {meta.get('routing_summary') or meta}")
    if meta.get("waterfall"):
        lines.append("")
        lines.append(str(meta["waterfall"]))
    if meta.get("bottleneck_rank"):
        lines.append("")
        lines.append("=== Bottleneck rank ===")
        for row in meta["bottleneck_rank"][:8]:
            lines.append(
                f"  #{row.get('rank')} {row.get('stage')}: "
                f"{row.get('sec')}s ({row.get('pct_of_stages')}%)"
            )
    return "\n".join(lines)
