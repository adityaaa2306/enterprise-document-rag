"""Unit tests for query latency tracker (no NIM)."""
import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.monitoring.query_latency import (
    QueryLatencyTracker,
    merge_latency,
    STAGE_DENSE,
    STAGE_QUERY_EMBED,
    STAGE_TOTAL,
)


def test_stage_context_manager():
    lat = QueryLatencyTracker()
    with lat.stage(STAGE_QUERY_EMBED):
        time.sleep(0.01)
    with lat.stage(STAGE_DENSE):
        time.sleep(0.005)
    d = lat.finish()
    assert STAGE_QUERY_EMBED in d["stages_ms"]
    assert d["stages_ms"][STAGE_QUERY_EMBED] >= 8
    assert STAGE_DENSE in d["stages_ms"]
    assert STAGE_TOTAL in d["stages_ms"]


def test_merge_latency():
    a = {"stages_ms": {"query_embed_ms": 10.0}, "meta": {"a": 1}}
    b = {"stages_ms": {"rerank_ms": 20.0}, "meta": {"b": 2}}
    m = merge_latency(a, b, total_ms=100.0)
    assert m["stages_ms"]["query_embed_ms"] == 10.0
    assert m["stages_ms"]["rerank_ms"] == 20.0
    assert m["stages_ms"][STAGE_TOTAL] == 100.0
    assert m["meta"]["a"] == 1 and m["meta"]["b"] == 2
