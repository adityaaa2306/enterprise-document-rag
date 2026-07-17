"""Helpers to attach quality scores onto model_run rows."""
from __future__ import annotations

from typing import Any, Dict, Optional

from src.eval.gpt_benchmark.quality.base import EvaluationInput, EvaluationResult
from src.eval.gpt_benchmark.quality.registry import get_evaluator


def evaluate_run_quality(
    *,
    question: str,
    reference_answer: Optional[str],
    candidate_answer: str,
    context: str,
    evaluator_id: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    evaluator = get_evaluator(evaluator_id)
    if dry_run:
        return EvaluationResult.skipped_result(
            "Dry-run — quality evaluation skipped (no generation).",
            evaluator_id=evaluator.evaluator_id,
        ).to_dict()

    result = evaluator.evaluate(
        EvaluationInput(
            question=question,
            reference_answer=reference_answer,
            candidate_answer=candidate_answer or "",
            context=context or "",
        )
    )
    return result.to_dict()
