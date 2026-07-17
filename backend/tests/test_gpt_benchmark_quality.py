"""Unit tests for offline benchmark quality evaluation (no API calls)."""
from __future__ import annotations

from src.eval.gpt_benchmark.dataset import (
    ATTENDANCE_SMOKE_DATASET,
    reference_for_question,
    resolve_dataset,
)
from src.eval.gpt_benchmark.quality.attach import evaluate_run_quality
from src.eval.gpt_benchmark.quality.base import EvaluationInput
from src.eval.gpt_benchmark.quality.composite import (
    DefaultCompositeEvaluator,
    LlmAsJudgeEvaluator,
)
from src.eval.gpt_benchmark.quality.insights import build_quality_insights
from src.eval.gpt_benchmark.quality.lexical import (
    exact_match_score,
    grounding_score,
    lexical_similarity_score,
)
from src.eval.gpt_benchmark.quality.registry import (
    DEFAULT_EVALUATOR_ID,
    get_evaluator,
    list_evaluator_ids,
)
from src.eval.gpt_benchmark.summary import aggregate_per_model


def test_registry_has_default_composite():
    assert DEFAULT_EVALUATOR_ID == "default_composite_v1"
    assert "default_composite_v1" in list_evaluator_ids()
    ev = get_evaluator()
    assert isinstance(ev, DefaultCompositeEvaluator)


def test_exact_match_and_lexical():
    assert exact_match_score("Hello World", "hello world") == 100.0
    assert exact_match_score("a", "b") == 0.0
    sim = lexical_similarity_score(
        "students track attendance percentages",
        "students monitor attendance percentage",
    )
    assert 40.0 <= sim <= 100.0


def test_composite_exact_match_scores_high():
    ev = DefaultCompositeEvaluator()
    ref = "The app tracks student attendance."
    result = ev.evaluate(
        EvaluationInput(
            question="What does it do?",
            reference_answer=ref,
            candidate_answer=ref,
            context="The app tracks student attendance in classes.",
        )
    )
    assert result.skipped is False
    assert result.quality_score == 100.0
    assert result.correctness == 100.0
    assert result.components["exact_match"] == 100.0
    assert 0.0 <= (result.groundedness or 0) <= 100.0


def test_composite_skips_without_reference():
    ev = DefaultCompositeEvaluator()
    result = ev.evaluate(
        EvaluationInput(
            question="Q?",
            reference_answer=None,
            candidate_answer="Something",
            context="ctx",
        )
    )
    assert result.skipped is True
    assert result.quality_score is None


def test_grounding_uses_context():
    score = grounding_score(
        "Attendance is marked present or absent per class.",
        "Students mark attendance as present or absent for each class session.",
    )
    assert score > 30.0


def test_llm_judge_stub_skips():
    stub = LlmAsJudgeEvaluator()
    out = stub.evaluate(
        EvaluationInput(
            question="q",
            reference_answer="r",
            candidate_answer="c",
            context="",
        )
    )
    assert out.skipped is True


def test_attach_flattens_scores():
    row = evaluate_run_quality(
        candidate_answer="The application helps students track class attendance.",
        reference_answer=ATTENDANCE_SMOKE_DATASET[0]["reference_answer"],
        question=ATTENDANCE_SMOKE_DATASET[0]["question"],
        context="Students track class attendance and percentages.",
        dry_run=False,
    )
    assert row["skipped"] is False
    assert row["quality_score"] is not None
    assert 0.0 <= row["quality_score"] <= 100.0


def test_attach_dry_run_skips():
    row = evaluate_run_quality(
        candidate_answer="",
        reference_answer="ref",
        question="q",
        context="c",
        dry_run=True,
    )
    assert row["skipped"] is True


def test_attendance_dataset_resolves():
    items = resolve_dataset(suite="smoke")
    assert len(items) >= 3
    ref = reference_for_question(
        ATTENDANCE_SMOKE_DATASET[0]["question"], items
    )
    assert ref and ref.get("reference_answer")
    by_id = resolve_dataset(suite="smoke", dataset_id="attendance_smoke")
    assert len(by_id) >= 3


def test_quality_insights_router_vs_best():
    lines = build_quality_insights(
        {
            "per_model": {
                "intelligent-router": {
                    "avg_quality_score": 85.0,
                    "total_estimated_api_cost_usd": 0.01,
                    "avg_latency_ms": 400.0,
                    "avg_estimated_co2e_g": 0.1,
                },
                "gpt-5.5": {
                    "avg_quality_score": 95.0,
                    "total_estimated_api_cost_usd": 0.05,
                    "avg_latency_ms": 900.0,
                    "avg_estimated_co2e_g": 0.4,
                },
            }
        }
    )
    assert any("highest average quality" in x for x in lines)
    assert any("Intelligent Router achieved" in x for x in lines)
    assert any("reducing estimated cost" in x for x in lines)


def test_summary_aggregates_quality():
    payload = {
        "metadata": {"models": ["gpt-5-nano", "intelligent-router"]},
        "questions": [
            {
                "question": "Q1",
                "reference_answer": "ref",
                "model_runs": [
                    {
                        "model": "gpt-5-nano",
                        "ok": True,
                        "latency_ms": 100,
                        "quality_score": 80.0,
                        "correctness": 80.0,
                        "completeness": 70.0,
                        "groundedness": 60.0,
                        "conciseness": 90.0,
                        "quality": {
                            "quality_score": 80.0,
                            "correctness": 80.0,
                            "completeness": 70.0,
                            "groundedness": 60.0,
                            "conciseness": 90.0,
                        },
                    },
                    {
                        "model": "intelligent-router",
                        "ok": True,
                        "latency_ms": 120,
                        "quality_score": 90.0,
                        "correctness": 90.0,
                        "completeness": 85.0,
                        "groundedness": 80.0,
                        "conciseness": 88.0,
                        "quality": {
                            "quality_score": 90.0,
                            "correctness": 90.0,
                            "completeness": 85.0,
                            "groundedness": 80.0,
                            "conciseness": 88.0,
                        },
                    },
                ],
            }
        ],
    }
    agg = aggregate_per_model(payload)
    assert agg["per_model"]["gpt-5-nano"]["avg_quality_score"] == 80.0
    assert agg["per_model"]["intelligent-router"]["avg_quality_score"] == 90.0
    q = agg["quality"]
    assert q["avg_quality_score"] == 85.0
    assert q["best_quality_model"]["model"] == "intelligent-router"
    assert q["insights"]
    assert q["scatter"]
