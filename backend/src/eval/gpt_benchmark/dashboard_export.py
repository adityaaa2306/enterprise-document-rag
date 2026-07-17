"""
Normalize benchmark aggregates into frontend-ready chart series.

The UI should consume this JSON as-is — no client-side aggregation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple


def _num(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pick_extreme(
    per_model: Dict[str, Dict[str, Any]],
    key: str,
    *,
    prefer: str = "min",
) -> Optional[Dict[str, Any]]:
    best_model = None
    best_val: Optional[float] = None
    for model, stats in per_model.items():
        val = _num(stats.get(key))
        if val is None:
            continue
        if best_val is None:
            best_model, best_val = model, val
            continue
        if prefer == "min" and val < best_val:
            best_model, best_val = model, val
        elif prefer == "max" and val > best_val:
            best_model, best_val = model, val
    if best_model is None:
        return None
    return {"model": best_model, "value": best_val, "metric": key}


def _series_from_models(
    models: Sequence[str],
    per_model: Dict[str, Dict[str, Any]],
    keys: Sequence[str],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for model in models:
        stats = per_model.get(model) or {}
        row: Dict[str, Any] = {"model": model}
        for k in keys:
            row[k] = stats.get(k)
        rows.append(row)
    return rows


def build_dashboard_payload(
    *,
    campaign_id: str,
    results_payload: Dict[str, Any],
    aggregates: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build normalized visualization JSON from a completed campaign run.
    """
    meta = results_payload.get("metadata") or {}
    summary = results_payload.get("summary") or {}
    per_model = dict((aggregates.get("per_model") or {}))
    models = list(meta.get("models") or list(per_model.keys()))
    workload = meta.get("workload") or summary.get("workload") or "interactive_rag"

    # Preserve declared model order; append any extras
    for m in per_model:
        if m not in models:
            models.append(m)

    reproducibility_questions: List[Dict[str, Any]] = []
    for q in results_payload.get("questions") or []:
        reproducibility_questions.append(
            {
                "question": q.get("question"),
                "document_id": q.get("document_id") or meta.get("document_id"),
                "context_hash": q.get("context_hash"),
                "prompt_hash": q.get("prompt_hash"),
                "chunk_count": q.get("chunk_count"),
                "prompt_version": q.get("prompt_version") or meta.get("prompt_version"),
                "retrieval_version": q.get("retrieval_version")
                or meta.get("retrieval_version"),
            }
        )

    latency_series = _series_from_models(
        models,
        per_model,
        ("avg_latency_ms", "p50_latency_ms", "p95_latency_ms"),
    )
    ttft_series = _series_from_models(models, per_model, ("avg_ttft_ms",))
    tps_series = _series_from_models(models, per_model, ("avg_tokens_per_sec",))
    token_series = _series_from_models(
        models,
        per_model,
        ("avg_prompt_tokens", "avg_completion_tokens"),
    )
    cost_series = _series_from_models(
        models,
        per_model,
        ("avg_estimated_api_cost_usd", "total_estimated_api_cost_usd"),
    )
    energy_series = _series_from_models(
        models,
        per_model,
        ("avg_estimated_energy_wh", "total_estimated_energy_wh"),
    )
    co2_series = _series_from_models(
        models,
        per_model,
        ("avg_estimated_co2e_g", "total_estimated_co2e_g"),
    )

    highlights = {
        "fastest_model": _pick_extreme(
            per_model, "avg_latency_ms", prefer="min"
        ),
        "highest_tokens_per_sec": _pick_extreme(
            per_model, "avg_tokens_per_sec", prefer="max"
        ),
        "lowest_estimated_cost": _pick_extreme(
            per_model, "total_estimated_api_cost_usd", prefer="min"
        ),
        "lowest_estimated_co2e": _pick_extreme(
            per_model, "avg_estimated_co2e_g", prefer="min"
        ),
        "best_quality_model": _pick_extreme(
            per_model, "avg_quality_score", prefer="max"
        ),
    }

    quality_agg = aggregates.get("quality") or {}
    quality_series = _series_from_models(
        models,
        per_model,
        (
            "avg_quality_score",
            "median_quality_score",
            "avg_correctness",
            "avg_completeness",
            "avg_groundedness",
            "avg_conciseness",
        ),
    )

    return {
        "schema_version": "1.2.0",
        "campaign_id": campaign_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "workload": workload,
        "models": models,
        "charts": {
            "latency_comparison": {
                "unit": "ms",
                "labels": list(models),
                "series": latency_series,
            },
            "ttft_comparison": {
                "unit": "ms",
                "labels": list(models),
                "series": ttft_series,
            },
            "tokens_per_sec": {
                "unit": "tokens/s",
                "labels": list(models),
                "series": tps_series,
            },
            "prompt_vs_completion_tokens": {
                "unit": "tokens",
                "labels": list(models),
                "series": token_series,
            },
            "estimated_cost": {
                "unit": "usd",
                "labels": list(models),
                "series": cost_series,
            },
            "estimated_energy": {
                "unit": "Wh",
                "labels": list(models),
                "series": energy_series,
            },
            "estimated_co2e": {
                "unit": "gCO2e",
                "labels": list(models),
                "series": co2_series,
            },
            "quality_overview": {
                "unit": "score_0_100",
                "labels": list(models),
                "series": quality_series,
            },
            "quality_distribution": quality_agg.get("distribution") or {},
            "quality_vs_latency": {
                "unit": "mixed",
                "points": [
                    {
                        "model": p.get("model"),
                        "quality": p.get("quality_score"),
                        "latency_ms": p.get("latency_ms"),
                    }
                    for p in (quality_agg.get("scatter") or [])
                ],
            },
            "quality_vs_cost": {
                "unit": "mixed",
                "points": [
                    {
                        "model": p.get("model"),
                        "quality": p.get("quality_score"),
                        "cost_usd": p.get("estimated_api_cost_usd"),
                    }
                    for p in (quality_agg.get("scatter") or [])
                ],
            },
            "quality_vs_co2e": {
                "unit": "mixed",
                "points": [
                    {
                        "model": p.get("model"),
                        "quality": p.get("quality_score"),
                        "co2e_g": p.get("estimated_co2e_g"),
                    }
                    for p in (quality_agg.get("scatter") or [])
                ],
            },
            "quality_vs_throughput": {
                "unit": "mixed",
                "points": [
                    {
                        "model": p.get("model"),
                        "quality": p.get("quality_score"),
                        "tokens_per_sec": p.get("tokens_per_sec"),
                    }
                    for p in (quality_agg.get("scatter") or [])
                ],
            },
        },
        "table": {
            "per_model": [
                {"model": m, **(per_model.get(m) or {})} for m in models
            ]
        },
        "highlights": highlights,
        "quality": {
            "avg_quality_score": quality_agg.get("avg_quality_score"),
            "median_quality_score": quality_agg.get("median_quality_score"),
            "best_quality_model": quality_agg.get("best_quality_model"),
            "n_scored": quality_agg.get("n_scored"),
            "distribution": quality_agg.get("distribution"),
            "insights": quality_agg.get("insights") or [],
            "evaluator": meta.get("quality_evaluator"),
        },
        "totals": {
            "total_api_cost_usd": summary.get("total_api_cost_usd")
            or summary.get("estimated_api_cost_usd"),
            "total_runtime_sec": summary.get("total_runtime_sec"),
            "total_prompt_tokens": summary.get("total_prompt_tokens"),
            "total_completion_tokens": summary.get("total_completion_tokens"),
            "total_tokens": summary.get("total_tokens"),
            "questions": summary.get("questions"),
            "avg_quality_score": quality_agg.get("avg_quality_score"),
            "median_quality_score": quality_agg.get("median_quality_score"),
        },
        "reproducibility": {
            "benchmark_version": meta.get("benchmark_version"),
            "workload": workload,
            "retrieval_version": meta.get("retrieval_version"),
            "document_freeze_version": meta.get("document_freeze_version"),
            "prompt_version": meta.get("prompt_version")
            or meta.get("prompt_template_version"),
            "document_id": meta.get("document_id"),
            "timestamp_utc": meta.get("timestamp_utc") or meta.get("timestamp"),
            "suite": meta.get("suite"),
            "questions": reproducibility_questions,
            "quality_evaluator": meta.get("quality_evaluator"),
        },
    }
