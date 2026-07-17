"""Evaluator registry for pluggable quality modules."""
from __future__ import annotations

from typing import Dict, List, Type

from src.eval.gpt_benchmark.quality.base import BenchmarkEvaluator
from src.eval.gpt_benchmark.quality.composite import (
    DeepEvalEvaluator,
    DefaultCompositeEvaluator,
    HumanEvalPlaceholder,
    LlmAsJudgeEvaluator,
    RagasEvaluator,
)

_REGISTRY: Dict[str, Type[BenchmarkEvaluator]] = {
    DefaultCompositeEvaluator.evaluator_id: DefaultCompositeEvaluator,
    # Documented extension points (instantiate only when implemented):
    LlmAsJudgeEvaluator.evaluator_id: LlmAsJudgeEvaluator,
    RagasEvaluator.evaluator_id: RagasEvaluator,
    DeepEvalEvaluator.evaluator_id: DeepEvalEvaluator,
    HumanEvalPlaceholder.evaluator_id: HumanEvalPlaceholder,
}

DEFAULT_EVALUATOR_ID = DefaultCompositeEvaluator.evaluator_id


def register_evaluator(cls: Type[BenchmarkEvaluator]) -> Type[BenchmarkEvaluator]:
    """Register / override an evaluator class by its ``evaluator_id``."""
    eid = getattr(cls, "evaluator_id", None) or cls.__name__
    _REGISTRY[str(eid)] = cls
    return cls


def get_evaluator(evaluator_id: str | None = None) -> BenchmarkEvaluator:
    eid = (evaluator_id or DEFAULT_EVALUATOR_ID).strip()
    cls = _REGISTRY.get(eid)
    if cls is None:
        known = ", ".join(sorted(_REGISTRY))
        raise KeyError(f"Unknown evaluator '{eid}'. Registered: {known}")
    return cls()


def list_evaluator_ids() -> List[str]:
    return sorted(_REGISTRY.keys())
