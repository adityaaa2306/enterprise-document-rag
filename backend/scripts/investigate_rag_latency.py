#!/usr/bin/env python3
"""
Live RAG performance investigation — collect measured latency from /rag-query
and write an evidence report. Does NOT change pipeline behavior.

Usage:
  $env:API_URL="http://127.0.0.1:8000"
  $env:DOCUMENT_ID="<completed document_id>"
  $env:E2E_EMAIL="..."
  $env:E2E_PASSWORD="..."
  cd backend
  .\\.venv\\Scripts\\python.exe scripts/investigate_rag_latency.py
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

import requests

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


def login(session: requests.Session, api: str, email: str, password: str) -> str:
    r = session.post(f"{api}/auth/login", json={"email": email, "password": password}, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"login failed: {r.status_code} {r.text[:300]}")
    token = r.json().get("access_token")
    if not token:
        raise RuntimeError("no access_token")
    return token


def run_one(session: requests.Session, api: str, token: str, document_id: str, query: str) -> Dict[str, Any]:
    t0 = time.perf_counter()
    r = session.post(
        f"{api}/rag-query",
        headers={"Authorization": f"Bearer {token}"},
        json={"document_id": document_id, "query": query},
        timeout=300,
    )
    wall = (time.perf_counter() - t0) * 1000.0
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    latency = body.get("latency") or {}
    return {
        "status": r.status_code,
        "query": query,
        "wall_client_ms": round(wall, 3),
        "stages_ms": dict(latency.get("stages_ms") or {}),
        "meta": latency.get("meta") or {},
        "model_used": body.get("model_used"),
        "skill": body.get("skill"),
        "answer_chars": len(body.get("answer") or ""),
        "error": None if r.status_code == 200 else body,
    }


def mean(xs: List[float]) -> float:
    return statistics.mean(xs) if xs else float("nan")


def main() -> int:
    api = os.environ.get("API_URL", "http://127.0.0.1:8000").rstrip("/")
    document_id = os.environ.get("DOCUMENT_ID", "").strip()
    email = os.environ.get("E2E_EMAIL", "").strip()
    password = os.environ.get("E2E_PASSWORD", "").strip()
    if not document_id or not email or not password:
        print("Set DOCUMENT_ID, E2E_EMAIL, E2E_PASSWORD", file=sys.stderr)
        return 2

    session = requests.Session()
    token = login(session, api, email, password)
    rows: List[Dict[str, Any]] = []
    for q in QUERIES:
        print(f"→ {q[:60]}...")
        row = run_one(session, api, token, document_id, q)
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
    report_lines: List[str] = []
    report_lines.append("# RAG Query Latency Investigation Report")
    report_lines.append("")
    report_lines.append(f"- Generated (UTC): `{ts}`")
    report_lines.append(f"- API: `{api}`")
    report_lines.append(f"- Document ID: `{document_id}`")
    report_lines.append(f"- Queries run: {len(rows)} (successful timed: {len(ok)})")
    report_lines.append(f"- Raw data: `{jsonl}`")
    report_lines.append("")
    report_lines.append("## Method")
    report_lines.append("")
    report_lines.append(
        "All stage timings are **measured** via `time.perf_counter()` on the server "
        "and returned in `latency.stages_ms`. Client wall clock is measured around "
        "the HTTP call. No estimated values are used for stage durations."
    )
    report_lines.append("")
    report_lines.append("## Stage table (mean / max over successful queries)")
    report_lines.append("")
    report_lines.append("| Stage | n | mean ms | max ms | mean % of total |")
    report_lines.append("|---|---:|---:|---:|---:|")

    totals = [float(r["stages_ms"].get("total_ms") or 0) for r in ok]
    mean_total = mean(totals) if totals else 0.0

    bottleneck_scores: List[tuple] = []
    for stage in STAGE_ORDER:
        vals = [float(r["stages_ms"][stage]) for r in ok if stage in r["stages_ms"]]
        if not vals:
            continue
        m = mean(vals)
        pct = (100.0 * m / mean_total) if mean_total > 0 and stage != "total_ms" else None
        report_lines.append(
            f"| `{stage}` | {len(vals)} | {m:.1f} | {max(vals):.1f} | "
            f"{'—' if pct is None else f'{pct:.1f}%'} |"
        )
        if stage not in ("total_ms", "retrieval_total_ms", "llm_generation_ms") and pct is not None:
            bottleneck_scores.append((stage, m, pct))

    report_lines.append("")
    report_lines.append("## Frontend vs backend")
    report_lines.append("")
    if ok:
        walls = [float(r["wall_client_ms"]) for r in ok]
        nets = [
            max(0.0, float(r["wall_client_ms"]) - float(r["stages_ms"].get("total_ms") or 0))
            for r in ok
        ]
        report_lines.append(f"- Mean client wall: **{mean(walls):.1f} ms**")
        report_lines.append(f"- Mean backend total: **{mean_total:.1f} ms**")
        report_lines.append(f"- Mean network/parse overhead (client−backend): **{mean(nets):.1f} ms**")
    report_lines.append("")

    report_lines.append("## Per-query waterfall (measured)")
    report_lines.append("")
    for i, r in enumerate(ok, 1):
        s = r["stages_ms"]
        report_lines.append(f"### Query {i}: {r['query'][:80]}")
        report_lines.append("")
        report_lines.append(f"- Model: `{r.get('model_used')}` · skill: `{r.get('skill')}`")
        report_lines.append(f"- Client wall: {r['wall_client_ms']:.1f} ms")
        meta = r.get("meta") or {}
        nim = meta.get("nim") or {}
        prompt = meta.get("prompt") or {}
        pipe = meta.get("pipeline_validation") or {}
        report_lines.append(
            f"- Pipeline clean (no ingest ops): **{pipe.get('clean', 'n/a')}** "
            f"(violations={pipe.get('ingest_ops_on_query_path')})"
        )
        if nim:
            report_lines.append(
                f"- NIM: ttft={nim.get('ttft_ms')} ttlt={nim.get('ttlt_ms')} "
                f"retries={nim.get('retry_count')} fallback={nim.get('fallback_used')} "
                f"http={nim.get('http_status')}"
            )
        if prompt:
            report_lines.append(
                f"- Prompt tokens: system={prompt.get('system_tokens')} "
                f"query={prompt.get('user_query_tokens')} "
                f"context={prompt.get('retrieved_context_tokens')} "
                f"final={prompt.get('final_prompt_tokens')} "
                f"output={prompt.get('output_tokens')}"
            )
        report_lines.append("")
        report_lines.append("```")
        for stage in STAGE_ORDER:
            if stage in s:
                report_lines.append(f"{stage:28} {float(s[stage]):10.1f} ms")
        report_lines.append("```")
        report_lines.append("")

    bottleneck_scores.sort(key=lambda x: x[2], reverse=True)
    top5 = bottleneck_scores[:5]
    report_lines.append("## Top 5 bottlenecks (by mean % of backend total)")
    report_lines.append("")
    for rank, (stage, ms, pct) in enumerate(top5, 1):
        report_lines.append(f"{rank}. **`{stage}`** — mean {ms:.1f} ms ({pct:.1f}% of backend total)")
    report_lines.append("")

    report_lines.append("## Root cause analysis")
    report_lines.append("")
    for stage, ms, pct in top5:
        cause = "Unknown"
        category = "Backend"
        confidence = "medium"
        if stage.startswith("llm_") or stage.startswith("nim_"):
            cause = (
                "NVIDIA NIM chat completion dominates wall time. "
                "TTFT/TTLT are measured via streaming instrumentation; "
                "the API still returns only after full generation."
            )
            category = "NVIDIA API / inference"
            confidence = "high" if pct >= 50 else "medium-high"
        elif stage == "rerank_ms":
            cause = "Second NIM call (reranker) over up to RAG_RERANK_N passages each query."
            category = "NVIDIA API / retrieval"
            confidence = "high"
        elif stage == "query_embed_ms":
            cause = "Query embedding NIM call (cache miss increases this)."
            category = "NVIDIA API / embedding"
            confidence = "high"
        elif "retrieve" in stage or stage in ("rrf_fuse_ms", "parent_expand_ms", "bm25_retrieve_ms"):
            cause = "Local retrieval work (Chroma/BM25/RRF)."
            category = "Retrieval"
            confidence = "high"
        elif stage in ("explainability_ms", "citations_ms", "postprocess_ms", "context_assemble_ms"):
            cause = "Local CPU post-processing / packing."
            category = "Backend"
            confidence = "high"
        report_lines.append(f"### `{stage}`")
        report_lines.append("")
        report_lines.append(f"- Impact: {ms:.1f} ms mean ({pct:.1f}%)")
        report_lines.append(f"- Category: **{category}**")
        report_lines.append(f"- Analysis: {cause}")
        report_lines.append(f"- Confidence: **{confidence}**")
        report_lines.append("")

    report_lines.append("## Pipeline validation (Phase 3)")
    report_lines.append("")
    cleans = [((r.get("meta") or {}).get("pipeline_validation") or {}).get("clean") for r in ok]
    report_lines.append(
        f"- All successful queries reported `pipeline_validation.clean=true`: "
        f"**{all(c is True for c in cleans) if cleans else 'n/a'}**"
    )
    report_lines.append(
        "- Guarded ingest ops (`store_chunks`, BM25 rebuild) log "
        "`QUERY_PATH_VIOLATION` if invoked during `/rag-query`."
    )
    report_lines.append("")
    report_lines.append("## Notes / non-goals")
    report_lines.append("")
    report_lines.append("- No optimizations were applied in this investigation.")
    report_lines.append(
        "- Frontend Insights panel now renders `latency.stages_ms` waterfall from the live response."
    )

    report_path = out_dir / f"REPORT_{ts}.md"
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    # Also copy to docs for easy discovery
    docs = Path(__file__).resolve().parents[1] / "docs" / "RAG_LATENCY_INVESTIGATION.md"
    docs.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    print(f"\nWrote {report_path}")
    print(f"Wrote {docs}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
