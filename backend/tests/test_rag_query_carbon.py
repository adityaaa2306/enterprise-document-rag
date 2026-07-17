"""Interactive RAG per-query carbon — independent of document workflow carbon."""
from src.carbon import assumptions as A
from src.carbon.accounting import (
    estimate_rag_query_carbon,
    estimate_rag_query_carbon_from_latency,
    estimate_workflow_carbon,
)
from src.carbon.energy_model import (
    apply_facility_overhead,
    energy_to_co2e_g,
    inference_joules,
    joules_to_kwh,
)


def _grid(**kwargs):
    base = {
        "intensity_gco2_kwh": 500.0,
        "zone": "TEST",
        "datetime": "2026-07-17T00:00:00.000Z",
        "updated_at": "2026-07-17T00:00:00.000Z",
        "source": "test",
        "is_estimated": True,
    }
    base.update(kwargs)
    return base


def test_rag_query_carbon_stage_sum_matches_total():
    report = estimate_rag_query_carbon(
        query_tokens=20,
        retrieved_context_tokens=700,
        prompt_tokens=900,
        output_tokens=150,
        inference_tier="heavy",
        retrieval_hits=2,
        grid=_grid(),
    )
    assert report["workload"] == "interactive_rag"
    assert report["independent_of_document_processing"] is True
    assert report["estimated_gco2e"] > 0
    assert report["estimated_energy_kwh"] > 0
    stages = report["stages_gco2e"]
    parts = (
        stages["query_embedding_gco2e"]
        + stages["retrieval_gco2e"]
        + stages["prompt_inference_gco2e"]
        + stages["completion_inference_gco2e"]
    )
    assert abs(parts - report["estimated_gco2e"]) < 1e-4
    assert abs(stages["llm_inference_gco2e"] - (
        stages["prompt_inference_gco2e"] + stages["completion_inference_gco2e"]
    )) < 1e-9


def test_rag_query_carbon_matches_energy_helpers():
    q, ctx, prompt, out = 10, 350, 400, 80
    tier = "medium"
    hits = 1
    intensity = 400.0

    embedding_j = q * A.EMBEDDING_J_PER_TOKEN
    retrieval_j = A.RETRIEVAL_BASE_J + hits * A.RETRIEVAL_J_PER_HIT
    prompt_j = inference_joules(prompt, tier=tier)
    completion_j = inference_joules(out, tier=tier)
    compute_j = embedding_j + retrieval_j + prompt_j + completion_j
    expected_kwh = joules_to_kwh(apply_facility_overhead(compute_j))
    expected_g = energy_to_co2e_g(expected_kwh, intensity)

    report = estimate_rag_query_carbon(
        query_tokens=q,
        retrieved_context_tokens=ctx,
        prompt_tokens=prompt,
        output_tokens=out,
        inference_tier=tier,
        retrieval_hits=hits,
        grid=_grid(intensity_gco2_kwh=intensity),
    )
    assert abs(report["estimated_energy_kwh"] - expected_kwh) < 1e-9
    assert abs(report["estimated_gco2e"] - expected_g) < 1e-6


def test_rag_carbon_independent_of_workflow_carbon():
    """Calling RAG estimator must not alter workflow report fields/shape."""
    class _Chunk:
        def __init__(self, content: str):
            self.content = content

    body = "chunk text " * 80
    chunks = [_Chunk(body) for _ in range(4)]
    state = {
        "chunks": chunks,
        "total_chunks": 4,
        "chunks_escalated": 0,
        "final_summary": "summary " * 40,
        "model_usage_chars": {
            "light": 0,
            "medium": sum(len(c.content) for c in chunks),
            "large": 2000,
        },
        "routing_decision": {
            "tier": "medium",
            "compile_tier": "heavy",
            "selected_model": "test",
        },
        "chunk_routing": [
            {"chunk_index": i, "tier": "medium", "model": "m", "reason": "t"}
            for i in range(4)
        ],
    }
    before = estimate_workflow_carbon("job-rag-iso", state, grid=_grid())
    rag = estimate_rag_query_carbon(
        query_tokens=15,
        retrieved_context_tokens=400,
        prompt_tokens=500,
        output_tokens=100,
        grid=_grid(),
    )
    after = estimate_workflow_carbon("job-rag-iso", state, grid=_grid())
    assert before["actual_cost_gco2e"] == after["actual_cost_gco2e"]
    assert before["baseline_cost_gco2e"] == after["baseline_cost_gco2e"]
    assert "actual_cost_gco2e" not in rag
    assert rag["estimated_gco2e"] != before["actual_cost_gco2e"]


def test_estimate_from_latency_prompt_meta():
    latency = {
        "meta": {
            "prompt": {
                "user_query_tokens": 12,
                "retrieved_context_tokens": 500,
                "final_prompt_tokens": 620,
                "output_tokens": 90,
            },
            "nim": {"tier": "heavy"},
        }
    }
    report = estimate_rag_query_carbon_from_latency(
        latency,
        query="ignored when meta present",
        answer="ignored",
        sources=["a", "b"],
        grid=_grid(),
    )
    assert report["tokens"]["prompt_tokens"] == 620
    assert report["tokens"]["output_tokens"] == 90
    assert report["tokens"]["retrieval_hits"] == 2
    assert report["inference_tier"] == "heavy"


def test_omit_query_embedding():
    with_emb = estimate_rag_query_carbon(
        query_tokens=100,
        retrieved_context_tokens=0,
        prompt_tokens=100,
        output_tokens=0,
        retrieval_hits=0,
        include_query_embedding=True,
        grid=_grid(),
    )
    without = estimate_rag_query_carbon(
        query_tokens=100,
        retrieved_context_tokens=0,
        prompt_tokens=100,
        output_tokens=0,
        retrieval_hits=0,
        include_query_embedding=False,
        grid=_grid(),
    )
    assert with_emb["estimated_gco2e"] > without["estimated_gco2e"]
    assert without["stages_gco2e"]["query_embedding_gco2e"] == 0.0
