#!/usr/bin/env python3
"""
Retrieval-only benchmark (no LLM generation).

Compares retrieval stage timings + chunk-id sets for quality validation.

Usage:
  cd backend
  $env:DOCUMENT_ID="..."
  .\\.venv\\Scripts\\python.exe scripts/bench_retrieval_opt.py
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents import models as models_mod
from src.core.config import settings
from src.memory import storage
from src.retrieval.service import RetrievalService

QUERIES = [
    "What is the main objective of this document?",
    "Summarize the key findings in 5 bullets.",
    "What methodology or approach was used?",
    "List the primary recommendations.",
    "What are the limitations or risks mentioned?",
    "Who are the stakeholders or intended audience?",
    "What metrics or KPIs are discussed?",
    "Explain the architecture or system design.",
    "What data sources were used?",
    "Describe the evaluation results.",
    "What future work is proposed?",
    "When were the major milestones completed?",
    "Compare the baseline versus the proposed approach.",
    "What carbon or energy-related claims are made?",
    "How does retrieval or RAG feature in this work?",
    "What models or tiers are recommended?",
    "What failure modes or edge cases are called out?",
    "Extract any numerical results or percentages.",
    "What is said about latency or performance?",
    "How is quality validated or measured?",
    "What open questions remain unanswered?",
    "Paraphrase the conclusion in one paragraph.",
    "Which sections discuss implementation details?",
    "Explain this like I'm a beginner.",
    "Find risks and limitations.",
]

STAGES = [
    "query_embed_ms",
    "dense_retrieve_ms",
    "bm25_retrieve_ms",
    "graph_seed_ms",
    "rrf_fuse_ms",
    "meta_lookup_ms",
    "rerank_ms",
    "parent_expand_ms",
    "retrieval_total_ms",
]


def pick_document_id() -> str:
    env = os.environ.get("DOCUMENT_ID", "").strip()
    if env:
        return env
    from src.db.session import get_session
    from src.db.models import JobModel
    from sqlalchemy import select, desc

    db = get_session()
    try:
        row = db.execute(
            select(JobModel)
            .where(JobModel.status == "complete")
            .order_by(desc(JobModel.created_at))
            .limit(1)
        ).scalar_one_or_none()
        if not row:
            raise SystemExit("No complete jobs; set DOCUMENT_ID")
        return row.id
    finally:
        db.close()


def pct(xs: List[float], p: float) -> float:
    if not xs:
        return float("nan")
    ys = sorted(xs)
    if len(ys) == 1:
        return ys[0]
    k = (len(ys) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(ys) - 1)
    if f == c:
        return ys[f]
    return ys[f] + (ys[c] - ys[f]) * (k - f)


def main() -> int:
    if not settings.NVIDIA_API_KEY:
        print("NVIDIA_API_KEY missing", file=sys.stderr)
        return 2

    storage.init_database(block_on_chroma=False)
    models_mod.load_nim_client()
    document_id = pick_document_id()
    print(f"document_id={document_id} queries={len(QUERIES)}")

    svc = RetrievalService()
    rows: List[Dict[str, Any]] = []

    # Warm caches with first query then discard timing for "cold" separate row
    print("Warmup...")
    warm = svc.search(QUERIES[0], document_id)
    warm_ids = [p.chunk_id for p in warm.passages]
    print(f"  warmup returned {len(warm_ids)} passages")

    for i, q in enumerate(QUERIES, 1):
        t0 = time.perf_counter()
        result = svc.search(q, document_id)
        wall = (time.perf_counter() - t0) * 1000.0
        stages = dict((result.debug.get("latency") or {}).get("stages_ms") or {})
        meta = dict((result.debug.get("latency") or {}).get("meta") or {})
        ids = [p.chunk_id for p in result.passages]
        scores = [float(p.score or 0) for p in result.passages]
        row = {
            "i": i,
            "query": q,
            "wall_ms": round(wall, 3),
            "stages_ms": stages,
            "meta": {
                k: meta.get(k)
                for k in (
                    "retrieval_mode",
                    "retrieved_chunks",
                    "reranked_chunks",
                    "doc_cache_chunks",
                    "doc_cache_load_ms",
                    "rerank_meta",
                    "embed_cache_hits",
                    "embed_cache_misses",
                )
            },
            "chunk_ids": ids,
            "scores": scores,
        }
        print(
            f"[{i:02d}] retrieval_total={stages.get('retrieval_total_ms')} "
            f"bm25={stages.get('bm25_retrieve_ms')} "
            f"parent={stages.get('parent_expand_ms')} "
            f"rerank={stages.get('rerank_ms')} "
            f"embed={stages.get('query_embed_ms')} "
            f"chunks={len(ids)}"
        )
        rows.append(row)

    out_dir = Path(__file__).resolve().parents[1] / "local_db" / "perf_investigation"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    jsonl = out_dir / f"retrieval_bench_{ts}.jsonl"
    with jsonl.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, default=str) + "\n")

    # Aggregate
    lines: List[str] = []
    lines.append("# Retrieval Optimization Benchmark Report")
    lines.append("")
    lines.append(f"- Generated (UTC): `{ts}`")
    lines.append(f"- Document: `{document_id}`")
    lines.append(f"- Queries: {len(rows)}")
    lines.append(f"- Raw: `{jsonl.as_posix()}`")
    lines.append("")
    lines.append("## Stage statistics (ms)")
    lines.append("")
    lines.append("| Stage | mean | p50 | p95 | max | stdev |")
    lines.append("|---|---:|---:|---:|---:|---:|")

    before = {
        "query_embed_ms": 892.0,
        "dense_retrieve_ms": 305.1,
        "bm25_retrieve_ms": 1600.0,
        "rrf_fuse_ms": 0.0,
        "rerank_ms": 408.0,
        "parent_expand_ms": 2495.0,
        "retrieval_total_ms": 11656.9,
        "context_assemble_ms": 4.4,
    }

    after_means: Dict[str, float] = {}
    for stage in STAGES:
        vals = [float(r["stages_ms"][stage]) for r in rows if stage in r["stages_ms"]]
        if not vals:
            continue
        m = statistics.mean(vals)
        after_means[stage] = m
        sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
        lines.append(
            f"| `{stage}` | {m:.1f} | {pct(vals, 50):.1f} | {pct(vals, 95):.1f} | "
            f"{max(vals):.1f} | {sd:.1f} |"
        )

    lines.append("")
    lines.append("## Before vs After (mean ms)")
    lines.append("")
    lines.append("| Metric | Before | After | Improvement |")
    lines.append("|---|---:|---:|---:|")
    for key, label in [
        ("query_embed_ms", "Query Embedding"),
        ("dense_retrieve_ms", "Chroma Search"),
        ("bm25_retrieve_ms", "BM25"),
        ("rrf_fuse_ms", "RRF"),
        ("parent_expand_ms", "Parent Expansion"),
        ("rerank_ms", "Reranking"),
        ("retrieval_total_ms", "Retrieval Total"),
    ]:
        b = before.get(key)
        a = after_means.get(key)
        if b is None or a is None:
            continue
        improv = ((b - a) / b * 100.0) if b > 0 else 0.0
        lines.append(f"| {label} | {b:.1f} | {a:.1f} | {improv:.1f}% |")

    totals = [float(r["stages_ms"].get("retrieval_total_ms") or 0) for r in rows]
    lines.append("")
    lines.append("## Success criteria")
    lines.append("")
    mean_ret = statistics.mean(totals) if totals else float("nan")
    mean_bm25 = after_means.get("bm25_retrieve_ms", float("nan"))
    mean_parent = after_means.get("parent_expand_ms", float("nan"))
    lines.append(f"- Retrieval total mean **{mean_ret:.1f} ms** (target <1000): "
                 f"{'PASS' if mean_ret < 1000 else 'FAIL'}")
    lines.append(f"- BM25 mean **{mean_bm25:.1f} ms** (target <50): "
                 f"{'PASS' if mean_bm25 < 50 else 'FAIL'}")
    lines.append(f"- Parent expand mean **{mean_parent:.1f} ms** (target <100): "
                 f"{'PASS' if mean_parent < 100 else 'FAIL'}")

    # Quality: Jaccard overlap of chunk-id sets across repeated paraphrases is not
    # available as before snapshot; instead report stability + rerank status.
    rerank_statuses = []
    for r in rows:
        rm = (r.get("meta") or {}).get("rerank_meta") or {}
        if isinstance(rm, dict):
            rerank_statuses.append(rm.get("status"))
    lines.append("")
    lines.append("## Rerank status distribution")
    lines.append("")
    for st in sorted(set(x for x in rerank_statuses if x)):
        lines.append(f"- `{st}`: {rerank_statuses.count(st)}")
    lines.append("")
    lines.append("## Quality notes")
    lines.append("")
    lines.append(
        "- Chunk IDs / scores captured per query in the JSONL for offline diffing."
    )
    lines.append(
        "- Warmup query chunk IDs: `" + ", ".join(warm_ids[:12]) + "`"
    )
    lines.append(
        "- No LLM prompting or generation code was modified in this phase."
    )

    report = "\n".join(lines) + "\n"
    report_path = out_dir / f"RETRIEVAL_OPT_{ts}.md"
    report_path.write_text(report, encoding="utf-8")
    docs = Path(__file__).resolve().parents[1] / "docs" / "RETRIEVAL_OPTIMIZATION.md"
    docs.write_text(report, encoding="utf-8")
    print(report)
    print(f"Wrote {report_path}")
    return 0 if mean_ret < 1000 else 1


if __name__ == "__main__":
    raise SystemExit(main())
