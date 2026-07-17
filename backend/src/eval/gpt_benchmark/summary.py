"""
Aggregate per-model metrics from a completed benchmark run.

Generates a companion summary JSON for dashboards / paper tables.
"""
from __future__ import annotations

import statistics
from typing import Any, Dict, List, Optional, Sequence


def _pct(xs: Sequence[float], p: float) -> Optional[float]:
    if not xs:
        return None
    s = sorted(float(x) for x in xs)
    if len(s) == 1:
        return round(s[0], 6)
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return round(s[f], 6)
    return round(s[f] + (s[c] - s[f]) * (k - f), 6)


def _avg(xs: Sequence[float]) -> Optional[float]:
    if not xs:
        return None
    return round(float(statistics.mean(xs)), 6)


def _collect(rows: Sequence[Dict[str, Any]], key: str) -> List[float]:
    out: List[float] = []
    for r in rows:
        if not r.get("ok"):
            continue
        if r.get("dry_run"):
            # Prefer upper-bound cost field for dry-run aggregates when present
            if key == "estimated_api_cost_usd" and "estimated_api_cost_usd_upper_bound" in r:
                out.append(float(r["estimated_api_cost_usd_upper_bound"]))
                continue
            if key == "prompt_tokens" and "prompt_tokens_estimate" in r:
                out.append(float(r["prompt_tokens_estimate"]))
                continue
            if key not in r or r.get(key) is None:
                continue
        val = r.get(key)
        if val is None:
            continue
        out.append(float(val))
    return out


def aggregate_per_model(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Build per-model aggregates from stored question → model_runs."""
    by_model: Dict[str, List[Dict[str, Any]]] = {}
    for q in payload.get("questions") or []:
        for run in q.get("model_runs") or []:
            mid = str(run.get("model") or run.get("model_requested") or "unknown")
            by_model.setdefault(mid, []).append(run)

    per_model: Dict[str, Any] = {}
    for model, rows in by_model.items():
        ok_rows = [r for r in rows if r.get("ok")]
        lat = _collect(ok_rows, "latency_ms")
        ttft = _collect(ok_rows, "ttft_ms")
        tps = _collect(ok_rows, "tokens_per_sec")
        prompt_toks = _collect(ok_rows, "prompt_tokens")
        completion_toks = _collect(ok_rows, "completion_tokens")
        costs = _collect(ok_rows, "estimated_api_cost_usd")
        energy = _collect(ok_rows, "estimated_energy_wh")
        if not energy:
            energy = _collect(ok_rows, "estimated_energy_kwh")
            energy = [e * 1000.0 for e in energy]
        co2 = _collect(ok_rows, "estimated_co2e_g")
        quality = _collect_quality(ok_rows, "quality_score")
        correctness = _collect_quality(ok_rows, "correctness")
        completeness = _collect_quality(ok_rows, "completeness")
        groundedness = _collect_quality(ok_rows, "groundedness")
        conciseness = _collect_quality(ok_rows, "conciseness")

        per_model[model] = {
            "n_runs": len(rows),
            "n_ok": len(ok_rows),
            "n_failed": len(rows) - len(ok_rows),
            "avg_latency_ms": _avg(lat),
            "p50_latency_ms": _pct(lat, 50),
            "p95_latency_ms": _pct(lat, 95),
            "avg_ttft_ms": _avg(ttft),
            "avg_tokens_per_sec": _avg(tps),
            "avg_prompt_tokens": _avg(prompt_toks),
            "avg_completion_tokens": _avg(completion_toks),
            "avg_estimated_api_cost_usd": _avg(costs),
            "total_estimated_api_cost_usd": round(sum(costs), 8) if costs else 0.0,
            "avg_estimated_energy_wh": _avg(energy),
            "total_estimated_energy_wh": round(sum(energy), 6) if energy else 0.0,
            "avg_estimated_co2e_g": _avg(co2),
            "total_estimated_co2e_g": round(sum(co2), 6) if co2 else 0.0,
            "avg_quality_score": _avg(quality),
            "median_quality_score": _pct(quality, 50),
            "avg_correctness": _avg(correctness),
            "avg_completeness": _avg(completeness),
            "avg_groundedness": _avg(groundedness),
            "avg_conciseness": _avg(conciseness),
            "n_quality_scored": len(quality),
        }

    meta = payload.get("metadata") or {}
    summary = payload.get("summary") or {}
    quality_block = _aggregate_quality(payload, per_model)
    return {
        "metadata": {
            "benchmark_version": meta.get("benchmark_version"),
            "prompt_version": meta.get("prompt_version")
            or meta.get("prompt_template_version"),
            "retrieval_version": meta.get("retrieval_version"),
            "timestamp_utc": meta.get("timestamp_utc"),
            "finished_utc": meta.get("finished_utc"),
            "suite": meta.get("suite"),
            "document_id": meta.get("document_id"),
            "models": meta.get("models"),
            "dry_run": meta.get("dry_run"),
            "results_path": meta.get("results_path"),
            "quality_evaluator": meta.get("quality_evaluator"),
        },
        "totals": {
            "total_api_cost_usd": summary.get("estimated_api_cost_usd")
            or summary.get("total_api_cost_usd"),
            "total_runtime_sec": summary.get("total_runtime_sec"),
            "questions": summary.get("questions"),
            "models": summary.get("models"),
            "total_prompt_tokens": summary.get("total_prompt_tokens"),
            "total_completion_tokens": summary.get("total_completion_tokens"),
            "total_tokens": summary.get("total_tokens"),
            "avg_quality_score": quality_block.get("avg_quality_score"),
            "median_quality_score": quality_block.get("median_quality_score"),
        },
        "per_model": per_model,
        "quality": quality_block,
    }


def _collect_quality(rows: Sequence[Dict[str, Any]], key: str) -> List[float]:
    out: List[float] = []
    for r in rows:
        if not r.get("ok") or r.get("dry_run"):
            continue
        q = r.get("quality") or {}
        if q.get("skipped"):
            continue
        val = q.get(key)
        if val is None:
            continue
        out.append(float(val))
    return out


def _aggregate_quality(
    payload: Dict[str, Any],
    per_model: Dict[str, Any],
) -> Dict[str, Any]:
    runs_flat: List[Dict[str, Any]] = []
    for q in payload.get("questions") or []:
        for run in q.get("model_runs") or []:
            runs_flat.append(run)
    all_scores = _collect_quality(runs_flat, "quality_score")

    best = None
    best_val: Optional[float] = None
    for model, stats in per_model.items():
        val = stats.get("avg_quality_score")
        if val is None:
            continue
        if best_val is None or float(val) > best_val:
            best_val = float(val)
            best = {"model": model, "value": best_val, "metric": "avg_quality_score"}

    # Per-run scatter points for quality vs efficiency charts
    scatter: List[Dict[str, Any]] = []
    for q in payload.get("questions") or []:
        for run in q.get("model_runs") or []:
            quality = run.get("quality") or {}
            if not run.get("ok") or run.get("dry_run") or quality.get("skipped"):
                continue
            qs = quality.get("quality_score")
            if qs is None:
                continue
            scatter.append(
                {
                    "model": run.get("model") or run.get("model_requested"),
                    "question": q.get("question"),
                    "quality_score": qs,
                    "latency_ms": run.get("latency_ms"),
                    "estimated_api_cost_usd": run.get("estimated_api_cost_usd"),
                    "estimated_co2e_g": run.get("estimated_co2e_g"),
                    "tokens_per_sec": run.get("tokens_per_sec"),
                }
            )

    from src.eval.gpt_benchmark.quality.insights import build_quality_insights

    return {
        "avg_quality_score": _avg(all_scores),
        "median_quality_score": _pct(all_scores, 50),
        "best_quality_model": best,
        "n_scored": len(all_scores),
        "distribution": {
            "min": round(min(all_scores), 2) if all_scores else None,
            "p25": _pct(all_scores, 25),
            "p50": _pct(all_scores, 50),
            "p75": _pct(all_scores, 75),
            "max": round(max(all_scores), 2) if all_scores else None,
        },
        "scatter": scatter,
        "insights": build_quality_insights({"per_model": per_model}),
    }
