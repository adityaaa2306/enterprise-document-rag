"""Default composite evaluator composing stdlib lexical metrics."""
from __future__ import annotations

from typing import List, Optional

from src.eval.gpt_benchmark.quality.base import (
    BenchmarkEvaluator,
    EvaluationInput,
    EvaluationResult,
)
from src.eval.gpt_benchmark.quality.lexical import (
    clamp_score,
    exact_match_score,
    grounding_score,
    length_ratio_score,
    lexical_similarity_score,
    token_recall_score,
)


class DefaultCompositeEvaluator(BenchmarkEvaluator):
    """
    Initial production evaluator for offline campaigns.

    Components (no embeddings / no LLM judge):
      - Exact Match
      - Lexical similarity (SequenceMatcher + token F1)
      - Length comparison
      - Citation / grounding against frozen context
    """

    evaluator_id = "default_composite_v1"

    def evaluate(self, payload: EvaluationInput) -> EvaluationResult:
        ref = (payload.reference_answer or "").strip()
        cand = (payload.candidate_answer or "").strip()
        ctx = payload.context or ""

        if not ref:
            return EvaluationResult.skipped_result(
                "No reference_answer for this question — quality skipped.",
                evaluator_id=self.evaluator_id,
            )
        if not cand:
            return EvaluationResult(
                quality_score=0.0,
                correctness=0.0,
                completeness=0.0,
                groundedness=0.0 if ctx.strip() else None,
                conciseness=0.0,
                notes=["Empty candidate answer."],
                evaluator_id=self.evaluator_id,
                components={"exact_match": 0.0, "lexical_similarity": 0.0},
            )

        em = exact_match_score(ref, cand)
        lex = lexical_similarity_score(ref, cand)
        completeness = token_recall_score(ref, cand)
        conciseness = length_ratio_score(ref, cand)
        ground_raw = grounding_score(cand, ctx)
        groundedness: Optional[float]
        notes: List[str] = []
        if ground_raw < 0:
            groundedness = None
            notes.append("Groundedness unavailable (empty frozen context).")
        else:
            groundedness = ground_raw

        correctness = clamp_score(0.35 * em + 0.65 * lex)

        dims = [correctness, completeness, conciseness]
        weights = [0.40, 0.25, 0.15]
        if groundedness is not None:
            dims.append(groundedness)
            weights.append(0.20)
        else:
            weights = [0.45, 0.30, 0.25]

        wsum = sum(weights)
        quality = clamp_score(
            sum(d * w for d, w in zip(dims, weights)) / max(1e-9, wsum)
        )

        if em >= 100.0:
            notes.append("Exact match with reference.")
        elif lex >= 80.0:
            notes.append("High lexical overlap with reference.")
        elif lex < 40.0:
            notes.append("Low lexical overlap — review for factual drift.")

        notes.append(
            "Lexical similarity uses stdlib SequenceMatcher + token F1 "
            "(not embedding cosine). Swap in a SemanticSimilarityEvaluator "
            "via the registry when embeddings are desired."
        )

        return EvaluationResult(
            quality_score=round(quality, 2),
            correctness=round(correctness, 2),
            completeness=round(completeness, 2),
            groundedness=None if groundedness is None else round(groundedness, 2),
            conciseness=round(conciseness, 2),
            notes=notes,
            evaluator_id=self.evaluator_id,
            components={
                "exact_match": round(em, 2),
                "lexical_similarity": round(lex, 2),
                "token_recall": round(completeness, 2),
                "length_ratio_score": round(conciseness, 2),
                "grounding_overlap": (
                    None if groundedness is None else round(groundedness, 2)
                ),
            },
        )


# Stubs documenting future plug-ins (not registered as defaults).
class LlmAsJudgeEvaluator(BenchmarkEvaluator):
    evaluator_id = "llm_as_judge"

    def evaluate(self, payload: EvaluationInput) -> EvaluationResult:
        return EvaluationResult.skipped_result(
            "LLM-as-a-Judge not implemented — register a concrete evaluator.",
            evaluator_id=self.evaluator_id,
        )


class RagasEvaluator(BenchmarkEvaluator):
    evaluator_id = "ragas"

    def evaluate(self, payload: EvaluationInput) -> EvaluationResult:
        return EvaluationResult.skipped_result(
            "RAGAS bridge not implemented.",
            evaluator_id=self.evaluator_id,
        )


class DeepEvalEvaluator(BenchmarkEvaluator):
    evaluator_id = "deepeval"

    def evaluate(self, payload: EvaluationInput) -> EvaluationResult:
        return EvaluationResult.skipped_result(
            "DeepEval bridge not implemented.",
            evaluator_id=self.evaluator_id,
        )


class HumanEvalPlaceholder(BenchmarkEvaluator):
    evaluator_id = "human"

    def evaluate(self, payload: EvaluationInput) -> EvaluationResult:
        return EvaluationResult.skipped_result(
            "Human evaluation is offline — ingest labeled scores separately.",
            evaluator_id=self.evaluator_id,
        )
