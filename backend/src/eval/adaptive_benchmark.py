"""
Offline adaptive routing benchmark harness.

Compares Always-Heavy / Always-Medium / Adaptive routing strategies on fixture
chunk features (mocked LLM). Optional ROUGE/BERTScore if installed.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Sequence

from src.agents.chunk_features import extract_chunk_features
from src.agents.quality_validation import validate_pair
from src.core.chunk_router import route_chunks, routing_distribution


def _fake_summary(text: str, tier: str) -> str:
    words = text.split()
    keep = max(8, int(len(words) * (0.35 if tier == "light" else 0.5 if tier == "medium" else 0.65)))
    return " ".join(words[:keep])


def run_strategy(
    chunks: Sequence[Any],
    *,
    strategy: str,
    cre_min_tier: str = "light",
) -> Dict[str, Any]:
    feats = extract_chunk_features(chunks)
    t0 = time.perf_counter()
    if strategy == "always_heavy":
        decisions = [
            type("D", (), {
                "tier": "heavy",
                "expected_carbon_g": 0.41,
                "to_dict": lambda self=None: {"tier": "heavy"},
            })()
            for _ in feats
        ]
        # simplify: build via router override
        from src.core.chunk_router import ChunkRouteDecision

        decisions = [
            ChunkRouteDecision(
                chunk_index=i,
                tier="heavy",
                model="heavy",
                reason="always_heavy",
                expected_quality=0.97,
                expected_carbon_g=0.41,
                expected_latency_ms=3200,
            )
            for i in range(len(feats))
        ]
    elif strategy == "always_medium":
        from src.core.chunk_router import ChunkRouteDecision

        decisions = [
            ChunkRouteDecision(
                chunk_index=i,
                tier="medium",
                model="medium",
                reason="always_medium",
                expected_quality=0.95,
                expected_carbon_g=0.18,
                expected_latency_ms=1600,
            )
            for i in range(len(feats))
        ]
    else:
        decisions = route_chunks(
            feats,
            cre_result={"min_tier": cre_min_tier},
            routing_decision={"tier": "medium", "selected_model": "m"},
            carbon_remaining_g=40.0,
            budget_enabled=True,
        )

    summaries = []
    carbon = 0.0
    confs = []
    for i, chunk in enumerate(chunks):
        text = chunk.content if hasattr(chunk, "content") else str(chunk)
        tier = decisions[i].tier
        summary = _fake_summary(text, tier)
        summaries.append(summary)
        carbon += float(decisions[i].expected_carbon_g)
        confs.append(validate_pair(text, summary).confidence)

    elapsed = (time.perf_counter() - t0) * 1000.0
    optional: Dict[str, Any] = {}
    try:
        from rouge_score import rouge_scorer  # type: ignore

        scorer = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=True)
        scores = []
        for chunk, summary in zip(chunks, summaries):
            text = chunk.content if hasattr(chunk, "content") else str(chunk)
            scores.append(scorer.score(text, summary)["rougeL"].fmeasure)
        optional["rougeL"] = round(sum(scores) / max(1, len(scores)), 4)
    except Exception:
        optional["rougeL"] = None
    try:
        import bert_score  # type: ignore

        optional["bertscore_available"] = True
    except Exception:
        optional["bertscore_available"] = False

    dist = routing_distribution(decisions)
    return {
        "strategy": strategy,
        "avg_confidence": round(sum(confs) / max(1, len(confs)), 4),
        "predicted_carbon_g": round(carbon, 4),
        "latency_ms": round(elapsed, 2),
        "routing": dist,
        **optional,
    }


def compare_strategies(chunks: Sequence[Any]) -> List[Dict[str, Any]]:
    return [
        run_strategy(chunks, strategy="always_heavy"),
        run_strategy(chunks, strategy="always_medium"),
        run_strategy(chunks, strategy="adaptive"),
    ]
