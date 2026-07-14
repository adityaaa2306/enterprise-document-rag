#!/usr/bin/env python3
"""
Benchmark NIM generation path (25 queries) — adaptive tokens + context cap.

Does not modify retrieval. Reports TTFT, tokens/sec, output tokens, generation time.

Usage (from backend/):
  python scripts/bench_generation_opt.py --document-id <uuid> [--out docs/GENERATION_BENCH.json]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

QUERIES = [
    "What is the main topic of this document?",
    "Summarize this document in one paragraph",
    "What are the key findings?",
    "Explain this like I'm a beginner",
    "Extract important numbers",
    "List all recommendations",
    "Compare the baseline versus the proposed approach",
    "Find risks and limitations",
    "What methodology was used?",
    "Who are the primary stakeholders?",
    "Define the reporting boundary",
    "How many sections does the document have?",
    "What is the conclusion?",
    "Analyze the trade-offs discussed",
    "Give a brief overview of results",
    "When was this work completed?",
    "What data sources are cited?",
    "Explain the evaluation metrics in detail",
    "List top three contributions",
    "How does the system reduce carbon?",
    "What is the difference between light and heavy models?",
    "Summarize the experimental setup",
    "What are the limitations?",
    "Provide a timeline of milestones",
    "Assess the implications of the findings",
]


def _pct(xs: List[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return float(s[f])
    return float(s[f] + (s[c] - s[f]) * (k - f))


def _stats(xs: List[float]) -> Dict[str, float]:
    if not xs:
        return {"avg": 0, "p50": 0, "p95": 0, "max": 0, "n": 0}
    return {
        "avg": round(statistics.mean(xs), 2),
        "p50": round(_pct(xs, 50), 2),
        "p95": round(_pct(xs, 95), 2),
        "max": round(max(xs), 2),
        "n": len(xs),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--document-id", required=True)
    ap.add_argument("--out", default=str(ROOT / "docs" / "GENERATION_BENCH.json"))
    ap.add_argument("--limit", type=int, default=25)
    args = ap.parse_args()

    from src.agents import models as models_mod
    from src.memory import storage
    from src.api.main import _run_rag_query
    from src.agents.response_planner import classify_response_length

    # Mirror API lifespan bootstrap (NIM client is not lazy)
    models_mod.load_all_models()
    storage.init_database(block_on_chroma=False)
    if models_mod.get_nim_client() is None:
        print("ERROR: NIM client not configured (check NVIDIA_API_KEY)")
        return 2

    rows: List[Dict[str, Any]] = []
    for q in QUERIES[: args.limit]:
        plan = classify_response_length(q)
        t0 = time.perf_counter()
        try:
            resp = _run_rag_query(document_id=args.document_id, query=q)
            wall = (time.perf_counter() - t0) * 1000.0
            lat = resp.latency or {}
            stages = lat.get("stages_ms") or {}
            meta = lat.get("meta") or {}
            prompt = meta.get("prompt") or {}
            nim = meta.get("nim") or {}
            rows.append(
                {
                    "query": q,
                    "query_type": plan.query_type,
                    "max_tokens_plan": plan.max_tokens,
                    "ok": True,
                    "wall_ms": round(wall, 1),
                    "retrieval_ms": stages.get("retrieval_total_ms"),
                    "ttft_ms": stages.get("llm_ttft_ms") or nim.get("ttft_ms"),
                    "ttlt_ms": stages.get("llm_ttlt_ms") or nim.get("ttlt_ms"),
                    "explain_ms": stages.get("explainability_ms"),
                    "total_ms": stages.get("total_ms"),
                    "prompt_tokens": prompt.get("final_prompt_tokens"),
                    "context_tokens": prompt.get("retrieved_context_tokens"),
                    "system_tokens": prompt.get("system_tokens"),
                    "output_tokens": prompt.get("output_tokens"),
                    "tokens_per_sec": prompt.get("tokens_per_sec") or nim.get("tokens_per_sec"),
                    "answer_chars": len(resp.answer or ""),
                }
            )
            print(
                f"OK type={plan.query_type:12} out={prompt.get('output_tokens')} "
                f"ttft={stages.get('llm_ttft_ms')} gen={stages.get('llm_ttlt_ms')} "
                f"tok/s={prompt.get('tokens_per_sec')} | {q[:48]}"
            )
        except Exception as e:
            rows.append({"query": q, "ok": False, "error": str(e)})
            print(f"FAIL {q[:48]}: {e}")

    ok = [r for r in rows if r.get("ok")]

    def col(key: str) -> List[float]:
        return [float(r[key]) for r in ok if r.get(key) is not None]

    by_type: Dict[str, List[float]] = {}
    for r in ok:
        by_type.setdefault(str(r.get("query_type")), []).append(
            float(r.get("output_tokens") or 0)
        )

    summary = {
        "n_ok": len(ok),
        "n_fail": len(rows) - len(ok),
        "retrieval_ms": _stats(col("retrieval_ms")),
        "ttft_ms": _stats(col("ttft_ms")),
        "ttlt_ms": _stats(col("ttlt_ms")),
        "total_ms": _stats(col("total_ms")),
        "wall_ms": _stats(col("wall_ms")),
        "explain_ms": _stats(col("explain_ms")),
        "prompt_tokens": _stats(col("prompt_tokens")),
        "context_tokens": _stats(col("context_tokens")),
        "output_tokens": _stats(col("output_tokens")),
        "tokens_per_sec": _stats(col("tokens_per_sec")),
        "avg_output_by_query_type": {
            k: round(statistics.mean(v), 1) if v else 0 for k, v in by_type.items()
        },
        "baseline_reference": {
            "generation_s": 23.8,
            "backend_total_s": 26.0,
            "ttft_ms": 700,
            "retrieval_ms": 540,
        },
    }

    out = {"summary": summary, "rows": rows}
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2))
    print(f"\nWrote {out_path}")
    return 0 if len(ok) >= max(1, args.limit // 2) else 1


if __name__ == "__main__":
    raise SystemExit(main())
