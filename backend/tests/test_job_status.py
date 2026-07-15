"""
Phase 2.0 — Pipeline Stabilization tests.

Unit: status normalization helper
Integration-style: JOB_STATUSES readiness matches /job-result gate
Regression: CRE / router modules still import and score (untouched)
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.job_status import (
    STATUS_COMPLETE,
    STATUS_ERROR,
    STATUS_PROCESSING,
    normalize_job_status,
    is_job_complete,
    is_job_ready_for_result,
)
from src.memory.document_ids import align_chunks_to_document_id
from src.core.cre import compute_crs
from src.core.intelligent_router import route, MODE_WEIGHTS


class _FakeChunk:
    """Minimal stand-in for triage.Chunk without importing unstructured."""

    def __init__(self, document_id: str, content: str):
        self.document_id = document_id
        self.content = content
        self.id = "x"
        self.chunk_index = 0
        self.type = "Text"

    def model_copy(self, update=None):
        update = update or {}
        return _FakeChunk(
            document_id=update.get("document_id", self.document_id),
            content=update.get("content", self.content),
        )


def test_normalize_job_status_aliases():
    from src.core.job_status import STATUS_PENDING, STATUS_CANCELLED

    assert normalize_job_status("complete") == STATUS_COMPLETE
    assert normalize_job_status("completed") == STATUS_COMPLETE
    assert normalize_job_status("COMPLETED") == STATUS_COMPLETE
    assert normalize_job_status("done") == STATUS_COMPLETE
    assert normalize_job_status("error") == STATUS_ERROR
    assert normalize_job_status("failed") == STATUS_ERROR
    assert normalize_job_status("processing") == STATUS_PROCESSING
    assert normalize_job_status("pending") == STATUS_PENDING
    assert normalize_job_status("cancelled") == STATUS_CANCELLED
    assert normalize_job_status("canceled") == STATUS_CANCELLED
    assert normalize_job_status(None) == STATUS_PENDING
    assert normalize_job_status("  ") == STATUS_PENDING


def test_is_job_complete():
    assert is_job_complete("complete") is True
    assert is_job_complete("completed") is True
    assert is_job_complete("processing") is False
    assert is_job_complete("error") is False


def test_is_job_ready_for_result_requires_payload():
    assert is_job_ready_for_result(None) is False
    assert is_job_ready_for_result({"status": "complete"}) is False
    assert is_job_ready_for_result({"status": "completed", "result": {}}) is False
    assert is_job_ready_for_result({
        "status": "complete",
        "result": {"document_id": "abc", "final_summary": "x"},
    }) is True
    assert is_job_ready_for_result({
        "status": "processing",
        "result": {"document_id": "abc"},
    }) is False
    # Stale in-memory pending must not block a durable summary payload
    assert is_job_ready_for_result({
        "status": "pending",
        "result": {"final_summary": "Ready now", "summary_ready": True},
    }) is True
    assert is_job_ready_for_result({
        "status": "processing",
        "result": {"summary_ready": True},
    }) is True


def test_align_chunks_to_document_id_pydantic_and_dict():
    job_id = "11111111-1111-1111-1111-111111111111"
    chunk = _FakeChunk(document_id="parsed_from_filename", content="Hello world")
    as_dict = {"content": "Dict chunk", "document_id": "other"}

    aligned = align_chunks_to_document_id(job_id, [chunk, as_dict])
    assert aligned[0].document_id == job_id
    assert aligned[0].content == "Hello world"
    assert aligned[1]["document_id"] == job_id
    assert aligned[1]["content"] == "Dict chunk"


def test_cre_router_regression_untouched():
    """Phase 1 CRE/router still function (no scoring changes in 2.0)."""
    from src.core.cre import Tier

    features = {
        "document_type": "general_text",
        "domain_label": "general",
        "risk_level": "low",
        "reasoning_score": 0.2,
        "structural_score": 0.1,
        "coherence_score": 0.1,
        "retrieval_confidence": 0.9,
        "ocr_confidence": 0.9,
        "chunk_count": 3,
        "carbon": {"grid_carbon_intensity_gco2_kwh": 400},
        "runtime": {"api_health": "healthy"},
    }
    cre = compute_crs(features)
    assert cre.min_tier == "light"
    for mode in ("eco", "balanced", "performance"):
        assert mode in MODE_WEIGHTS
        d = route(cre, features, mode=mode)
        assert d.selected_model
        # Router may pick a higher tier for utility; must never go below CRE floor
        assert Tier.from_str(d.tier).rank() >= Tier.from_str(cre.min_tier).rank()


def test_smart_routing_preference_keys_and_aliases():
    """Smart Routing UX: new preference keys + legacy aliases resolve and respect floors."""
    from src.core.cre import Tier
    from src.core.intelligent_router import normalize_routing_preference

    assert normalize_routing_preference(None) == "automatic"
    assert normalize_routing_preference("automatic") == "automatic"
    assert normalize_routing_preference("auto") == "automatic"
    assert normalize_routing_preference("smart") == "automatic"
    assert normalize_routing_preference("fastest") == "fastest"
    assert normalize_routing_preference("lowest_cost") == "lowest_cost"
    assert normalize_routing_preference("lowest_carbon") == "lowest_carbon"
    assert normalize_routing_preference("highest_quality") == "highest_quality"
    assert normalize_routing_preference("eco") == "eco"
    assert normalize_routing_preference("balanced") == "balanced"
    assert normalize_routing_preference("performance") == "performance"
    assert normalize_routing_preference("quality") == "quality"
    assert normalize_routing_preference("max quality") == "highest_quality"
    assert normalize_routing_preference("max_quality") == "highest_quality"
    assert normalize_routing_preference("unknown_mode_xyz") == "automatic"

    for key in (
        "automatic",
        "fastest",
        "lowest_cost",
        "lowest_carbon",
        "highest_quality",
        "eco",
        "balanced",
        "performance",
        "quality",
    ):
        assert key in MODE_WEIGHTS

    features = {
        "document_type": "general_text",
        "domain_label": "general",
        "risk_level": "low",
        "reasoning_score": 0.2,
        "structural_score": 0.1,
        "coherence_score": 0.1,
        "retrieval_confidence": 0.9,
        "ocr_confidence": 0.9,
        "chunk_count": 3,
        "carbon": {"grid_carbon_intensity_gco2_kwh": 400},
        "runtime": {"api_health": "healthy"},
    }
    cre = compute_crs(features)
    for mode in ("automatic", "fastest", "lowest_cost", "lowest_carbon", "highest_quality"):
        d = route(cre, features, mode=mode)
        assert d.selected_model
        assert Tier.from_str(d.tier).rank() >= Tier.from_str(cre.min_tier).rank()


if __name__ == "__main__":
    test_normalize_job_status_aliases()
    test_is_job_complete()
    test_is_job_ready_for_result_requires_payload()
    test_align_chunks_to_document_id_pydantic_and_dict()
    test_cre_router_regression_untouched()
    test_smart_routing_preference_keys_and_aliases()
    print("ALL Phase 2.0 TESTS PASSED")
