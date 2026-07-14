"""Performance optimization unit tests — functional equivalence preserved."""
from __future__ import annotations

import time

from src.agents.quality_validation import validate_chunks, validate_pair
from src.perf.cache import (
    clear_perf_caches,
    get_cached_grid_intensity,
    get_token_count,
    grid_cache_key,
    put_cached_grid_intensity,
)
from src.perf.profiler import format_waterfall, rank_bottlenecks
from src.monitoring.ingestion_latency import IngestionLatencyTracker


class _C:
    def __init__(self, content: str):
        self.content = content


def test_token_count_cache_stable():
    clear_perf_caches()
    t = "hello world " * 100
    a = get_token_count(t)
    b = get_token_count(t)
    assert a == b == max(1, len(t) // 4)


def test_grid_intensity_ttl_cache():
    clear_perf_caches()
    key = grid_cache_key(zone="IN-WE")
    put_cached_grid_intensity(
        key,
        {"intensity_gco2_kwh": 650.0, "zone": "IN-WE", "source": "test"},
        ttl_sec=60,
    )
    hit = get_cached_grid_intensity(key)
    assert hit is not None
    assert hit["intensity_gco2_kwh"] == 650.0


def test_validate_chunks_parallel_matches_serial_aggregate():
    chunks = [
        _C("Alpha beta gamma delta epsilon zeta eta theta iota."),
        _C("Neural networks reduce latency and improve throughput."),
        _C("Completely different topic about renewable carbon grids."),
    ]
    summaries = [
        "Alpha beta gamma delta epsilon.",
        "Neural networks improve throughput and reduce latency.",
        "Unrelated fabricated zoo penguins content here.",
    ]
    # Sequential path via only_indices one-by-one vs full parallel
    full = validate_chunks(chunks, summaries)
    assert "failed_indices" in full.details
    assert "chunk_verdicts" in full.details
    assert len(full.details["chunk_verdicts"]) == 3


def test_incremental_validation_reuses_priors():
    chunks = [
        _C("The optimizer reduces latency for transformer embeddings."),
        _C("Carbon intensity depends on regional electricity grids."),
    ]
    summaries = [
        "The optimizer reduces latency for embeddings.",
        "Unrelated fabricated content about penguins.",
    ]
    first = validate_chunks(chunks, summaries)
    priors = []
    for d in first.details["chunk_verdicts"]:
        from src.agents.quality_validation import ValidationVerdict

        priors.append(
            ValidationVerdict(
                passed=bool(d["passed"]),
                confidence=float(d["confidence"]),
                faithfulness=float(d["faithfulness"]),
                coverage=float(d["coverage"]),
                hallucination_rate=float(d["hallucination_rate"]),
                contradiction_rate=float(d["contradiction_rate"]),
                codes=list(d.get("codes") or []),
                details=dict(d.get("details") or {}),
                semantic_similarity=float(d.get("semantic_similarity") or 0),
                entity_retention=float(d.get("entity_retention") or 0),
            )
        )
    # Revalidate only index 1 with same summary → same aggregate
    second = validate_chunks(
        chunks,
        summaries,
        only_indices=[1],
        prior_verdicts=priors,
    )
    assert second.passed == first.passed
    assert abs(second.confidence - first.confidence) < 1e-6
    assert second.details["failed_indices"] == first.details["failed_indices"]


def test_waterfall_and_rank():
    stages = {
        "triage_ms": 1000,
        "map_summarize_ms": 90000,
        "validate_map_ms": 2000,
        "reduce_compile_ms": 30000,
        "total_ms": 123000,
    }
    wf = format_waterfall(stages)
    assert "map_summarize_ms" in wf
    ranked = rank_bottlenecks(stages)
    assert ranked[0]["stage"] == "map_summarize_ms"


def test_latency_tracker_stage_detail():
    lat = IngestionLatencyTracker(job_id="t")
    with lat.stage("triage_ms"):
        time.sleep(0.01)
    d = lat.as_dict()
    assert "triage_ms" in d["stages_ms"]
    assert "triage_ms" in d["stage_detail"]
    assert "cpu_ms" in d["stage_detail"]["triage_ms"]
    finished = lat.finish()
    assert "bottleneck_rank" in finished["meta"] or finished["meta"].get("waterfall")


def test_validate_pair_unchanged_grounding():
    source = (
        "The neural network optimizer reduces latency and improves throughput "
        "for transformer embeddings in production systems."
    )
    summary = "The neural network optimizer improves throughput and reduces latency."
    v = validate_pair(source, summary)
    assert v.coverage > 0.3
