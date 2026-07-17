"""
Modular quality evaluation for offline benchmarks.

Evaluators are pluggable; production RAG / ResponseAgent quality code is unused.
"""
from __future__ import annotations

from src.eval.gpt_benchmark.quality.base import (
    BenchmarkEvaluator,
    EvaluationInput,
    EvaluationResult,
)
from src.eval.gpt_benchmark.quality.composite import DefaultCompositeEvaluator
from src.eval.gpt_benchmark.quality.registry import (
    get_evaluator,
    list_evaluator_ids,
    register_evaluator,
)

__all__ = [
    "BenchmarkEvaluator",
    "EvaluationInput",
    "EvaluationResult",
    "DefaultCompositeEvaluator",
    "get_evaluator",
    "list_evaluator_ids",
    "register_evaluator",
]
