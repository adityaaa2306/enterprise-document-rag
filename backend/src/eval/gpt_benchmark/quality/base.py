"""
Quality evaluator contracts.

Future plug-ins (LLM-as-a-Judge, RAGAS, DeepEval, human labels) should
implement ``BenchmarkEvaluator`` and register via ``register_evaluator``.
Do not call production OpenAI / NIM from evaluators unless explicitly designed.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class EvaluationInput:
    question: str
    reference_answer: Optional[str]
    candidate_answer: str
    context: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluationResult:
    """All dimension scores are normalized to 0–100 (None = unavailable)."""

    quality_score: Optional[float]
    correctness: Optional[float]
    completeness: Optional[float]
    groundedness: Optional[float]
    conciseness: Optional[float]
    notes: List[str] = field(default_factory=list)
    evaluator_id: str = ""
    components: Dict[str, Any] = field(default_factory=dict)
    skipped: bool = False
    skip_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def skipped_result(reason: str, evaluator_id: str = "") -> "EvaluationResult":
        return EvaluationResult(
            quality_score=None,
            correctness=None,
            completeness=None,
            groundedness=None,
            conciseness=None,
            notes=[reason],
            evaluator_id=evaluator_id,
            skipped=True,
            skip_reason=reason,
        )


class BenchmarkEvaluator(ABC):
    """
    Pluggable quality evaluator.

    Implementations must be side-effect free w.r.t. production systems and
    should not call LLMs unless that is the evaluator's explicit purpose
    (e.g. a future LLM-as-a-Judge module).
    """

    evaluator_id: str = "base"

    @abstractmethod
    def evaluate(self, payload: EvaluationInput) -> EvaluationResult:
        """Score one candidate answer against optional reference + context."""

    def evaluate_batch(
        self, payloads: List[EvaluationInput]
    ) -> List[EvaluationResult]:
        return [self.evaluate(p) for p in payloads]
