#!/usr/bin/env python3
"""
In-process RAG latency investigation (no HTTP auth required).

Calls _run_rag_query directly against a completed document_id so we can
collect measured stages_ms even if the uvicorn process is mid-reload.

Usage:
  cd backend
  .\\.venv\\Scripts\\python.exe scripts/investigate_rag_latency_local.py
  # or:
  $env:DOCUMENT_ID="..."
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

# Ensure backend package imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents import models as models_mod
from src.api.main import _run_rag_query
from src.core.config import settings
from src.memory import storage

QUERIES = [
    "What is the main objective of this document?",
    "Summarize the key findings in 5 bullets.",
    "What are the limitations or risks mentioned?",
    "Extract any numerical results or percentages.",
    "Explain this like I'm a beginner.",
]

STAGE_ORDER = [
    "query_embed_ms",
    "dense_retrieve_ms",
    "bm25_retrieve_ms",
    "rrf_fuse_ms",
    "rerank_ms",
    "parent_expand_ms",
    "retrieval_total_ms",
    "context_assemble_ms",
    "nim_network_ms",
    "llm_ttft_ms",
    "llm_ttlt_ms",
    "llm_generation_ms",
    "postprocess_ms",
    "explainability_ms",
    "citations_ms",
    "total_ms",
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
            raise SystemExit("No complete jobs found; set DOCUMENT_ID")
        return row.id
    finally:
        db.close()


def mean(xs: List[float]) -> float:
    return statistics.mean(xs) if xs else float("nan")


def main() -> int:
    if not settings.NVIDIA_API_KEY:
        print("NVIDIA_API_KEY missing", file=sys.stderr)
        return 2

    storage.init_database(block_on_chroma=False)
    models_mod.load_nim_client()

    document_id = pick_document_id()
    print(f"document_id={document_id}")

    rows: List[Dict[str, Any]] = []
    for q in QUERIES:
        print(f"→ {q[:70]}...")
        t0 = time.perf_counter()
        try:
            resp = _run_rag_query(document_id=document_id, query=q)
            wall = (time.perf_counter() - t0) * 1000.0
            latency = resp.latency or {}
            row = {
                "status": 200,
                "query": q,
                "wall_client_ms": round(wall, 3),
                "stages_ms": dict((latency or {}).get("stages_ms") or {}),
                "meta": (latency or {}).get("meta") or {},
                "model_used": resp.model_used,
                "skill": resp.skill,
                "answer_chars": len(resp.answer or ""),
            }
        except Exception as e:
            wall = (time.perf_counter() - t0) * 1000.0
            print(f"  FAIL {type(e).__name__}: {e}")
            row = {
                "status": 500,
                "query": q,
                "wall_client_ms": round(wall, 3),
                "stages_ms": {},
                "meta": {},
                "error": str(e)[:500],
            }
        print(
            f"  status={row['status']} wall={row['wall_client_ms']:.0f}ms "
            f"backend={row['stages_ms'].get('total_ms')} "
            f"ttlt={row['stages_ms'].get('llm_ttlt_ms')} model={row.get('model_used')}"
        )
        rows.append(row)

    out_dir = Path(__file__).resolve().parents[1] / "local_db" / "perf_investigation"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    jsonl = out_dir / f"live_queries_{ts}.jsonl"
    with jsonl.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, default=str) + "\n")

    ok = [r for r in rows if r["status"] == 200 and r.get("stages_ms")]
    lines: List[str] = []
    lines.append("# RAG Query Latency Investigation Report")
    lines.append("")
    lines.append(f"- Generated (UTC): `{ts}`")
    lines.append("- Mode: in-process `_run_rag_query` (measured stages; no auth overhead)")
    lines.append(f"- Document ID: `{document_id}`")
    lines.append(f"- Queries run: {len(rows)} (successful timed: {len(ok)})")
    lines.append(f"- Raw data: `{jsonl.as_posix()}`")
    lines.append("")
    lines.append("## Method")
    lines.append("")
    lines.append(
        "Stage timings are measured with `time.perf_counter()` inside retrieval, "
        "context assembly, NIM stream-measure (TTFT/TTLT), explainability, and "
        "returned in `latency.stages_ms`. Values below are **not estimates**."
    )
    lines.append("")
    lines.append("## Stage table (mean / max)")
    lines.append("")
    lines.append("| Stage | n | mean ms | max ms | mean % of total |")
    lines.append("|---|---:|---:|---:|---:|")

    totals = [float(r["stages_ms"].get("total_ms") or 0) for r in ok]
    mean_total = mean(totals) if totals else 0.0
    bottleneck_scores = []
    for stage in STAGE_ORDER:
        vals = [float(r["stages_ms"][stage]) for r in ok if stage in r["stages_ms"]]
        if not vals:
            continue
        m = mean(vals)
        pct = (100.0 * m / mean_total) if mean_total > 0 and stage != "total_ms" else None
        lines.append(
            f"| `{stage}` | {len(vals)} | {m:.1f} | {max(vals):.1f} | "
            f"{'—' if pct is None else f'{pct:.1f}%'} |"
        )
        if stage not in ("total_ms", "retrieval_total_ms", "llm_generation_ms") and pct is not None:
            bottleneck_scores.append((stage, m, pct))

    lines.append("")
    lines.append("## Client vs backend (in-process wall ≈ backend)")
    lines.append("")
    if ok:
        walls = [float(r["wall_client_ms"]) for r in ok]
        lines.append(f"- Mean call wall: **{mean(walls):.1f} ms** ({mean(walls)/1000:.2f} s)")
        lines.append(f"- Mean backend total: **{mean_total:.1f} ms** ({mean_total/1000:.2f} s)")
    lines.append("")

    lines.append("## Per-query detail")
    lines.append("")
    for i, r in enumerate(ok, 1):
        s = r["stages_ms"]
        meta = r.get("meta") or {}
        nim = meta.get("nim") or {}
        prompt = meta.get("prompt") or {}
        pipe = meta.get("pipeline_validation") or {}
        emb = meta.get("embedding") or {}
        lines.append(f"### Query {i}: {r['query']}")
        lines.append("")
        lines.append(f"- Model: `{r.get('model_used')}` · skill `{r.get('skill')}`")
        lines.append(f"- Wall: {r['wall_client_ms']:.1f} ms")
        lines.append(
            f"- Pipeline clean: **{pipe.get('clean')}** violations={pipe.get('ingest_ops_on_query_path')}"
        )
        if nim:
            lines.append(
                f"- NIM measured: first_byte={nim.get('first_byte_ms')} "
                f"ttft={nim.get('ttft_ms')} ttlt={nim.get('ttlt_ms')} "
                f"inference={nim.get('inference_ms')} retries={nim.get('retry_count')} "
                f"fallback={nim.get('fallback_used')} http={nim.get('http_status')}"
            )
            if nim.get("retry_reasons"):
                lines.append(f"- Retry reasons: `{nim.get('retry_reasons')}`")
        if prompt:
            lines.append(
                f"- Tokens: system={prompt.get('system_tokens')} "
                f"query={prompt.get('user_query_tokens')} "
                f"context={prompt.get('retrieved_context_tokens')} "
                f"final={prompt.get('final_prompt_tokens')} "
                f"output={prompt.get('output_tokens')}"
            )
        if emb:
            lines.append(
                f"- Embedding: model={emb.get('embedding_model')} "
                f"hits={emb.get('cache_hits')} misses={emb.get('cache_misses')} "
                f"api_ms={emb.get('embed_api_ms')} dim={emb.get('dim')}"
            )
        lines.append("")
        lines.append("```")
        for stage in STAGE_ORDER:
            if stage in s:
                lines.append(f"{stage:28} {float(s[stage]):10.1f} ms")
        lines.append("```")
        lines.append("")

    bottleneck_scores.sort(key=lambda x: x[2], reverse=True)
    top5 = bottleneck_scores[:5]
    lines.append("## Top 5 bottlenecks")
    lines.append("")
    for rank, (stage, ms, pct) in enumerate(top5, 1):
        lines.append(f"{rank}. **`{stage}`** — {ms:.1f} ms mean ({pct:.1f}% of backend total)")
    lines.append("")

    lines.append("## Root cause analysis")
    lines.append("")
    for stage, ms, pct in top5:
        if stage.startswith("llm_") or stage.startswith("nim_"):
            category, confidence = "NVIDIA API / inference", "high"
            analysis = (
                "Chat completion wall time on NVIDIA NIM. TTFT/TTLT measured via "
                "streaming instrumentation; response is fully accumulated before return."
            )
        elif stage == "rerank_ms":
            category, confidence = "NVIDIA API / retrieval", "high"
            analysis = "Reranker NIM call over up to RAG_RERANK_N candidate passages every query."
        elif stage == "query_embed_ms":
            category, confidence = "NVIDIA API / embedding", "high"
            analysis = "Query embedding NIM call; cache hits reduce embed_api_ms to ~0."
        elif stage in ("dense_retrieve_ms", "bm25_retrieve_ms", "rrf_fuse_ms", "parent_expand_ms"):
            category, confidence = "Retrieval (local)", "high"
            analysis = "Local Chroma/BM25/RRF/parent-expand work."
        else:
            category, confidence = "Backend local", "medium-high"
            analysis = "Local CPU stage (assemble / explainability / post-process)."
        lines.append(f"### `{stage}` ({pct:.1f}%)")
        lines.append("")
        lines.append(f"- Category: **{category}**")
        lines.append(f"- Analysis: {analysis}")
        lines.append(f"- Confidence: **{confidence}**")
        lines.append("")

    lines.append("## Phase 3 — ingest ops during query")
    lines.append("")
    cleans = [((r.get("meta") or {}).get("pipeline_validation") or {}).get("clean") for r in ok]
    lines.append(f"- All queries clean: **{all(c is True for c in cleans) if cleans else 'n/a'}**")
    lines.append(
        "- Guards active on `store_chunks` and BM25 rebuild; violations would appear in "
        "`pipeline_validation.ingest_ops_on_query_path`."
    )
    lines.append("")
    lines.append("## Non-goals")
    lines.append("")
    lines.append("- No optimizations, caching changes, or retrieval redesign were performed.")

    report = "\n".join(lines) + "\n"
    report_path = out_dir / f"REPORT_{ts}.md"
    report_path.write_text(report, encoding="utf-8")
    docs = Path(__file__).resolve().parents[1] / "docs" / "RAG_LATENCY_INVESTIGATION.md"
    docs.write_text(report, encoding="utf-8")
    print(f"\nWrote {report_path}")
    print(f"Wrote {docs}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
