"""Unit tests for ingestion latency tracker."""
import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.monitoring.ingestion_latency import (
    IngestionLatencyTracker,
    STAGE_MAP_SUMMARIZE,
    STAGE_TRIAGE,
    format_latency_table,
    summarize_durations_ms,
)


def test_stage_and_chunk_stats():
    lat = IngestionLatencyTracker(job_id="j1")
    with lat.stage(STAGE_TRIAGE):
        time.sleep(0.01)
    lat.worker_enter()
    lat.record_chunk_call(
        {
            "chunk_index": 0,
            "tier": "medium",
            "model_id": "m",
            "queue_ms": 1.0,
            "call_ms": 100.0,
            "success": True,
            "retry_count": 2,
            "attempt_count": 3,
            "http_status": None,
        }
    )
    lat.record_chunk_call(
        {
            "chunk_index": 1,
            "tier": "medium",
            "model_id": "m",
            "queue_ms": 50.0,
            "call_ms": 200.0,
            "success": False,
            "retry_count": 0,
            "attempt_count": 1,
            "http_status": 408,
        }
    )
    lat.worker_exit()
    with lat.stage(STAGE_MAP_SUMMARIZE):
        time.sleep(0.005)
    d = lat.finish()
    assert STAGE_TRIAGE in d["stages_ms"]
    assert d["map_chunk_stats"]["call_ms"]["n"] == 2
    assert d["map_chunk_stats"]["failures"] == 1
    assert d["pool_peak_active"] >= 1
    table = format_latency_table(d)
    assert "map_summarize_ms" in table


def test_summarize_durations():
    s = summarize_durations_ms([10.0, 20.0, 30.0, 40.0])
    assert s["n"] == 4
    assert s["mean"] == 25.0
