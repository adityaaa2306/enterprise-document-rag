#!/usr/bin/env python3
"""
Batch RAG latency capture — runs ~25 representative queries and prints a stage table.

Prereqs:
  - API running (local or remote) with a completed document
  - Auth credentials (signup/login)

Usage (PowerShell):
  $env:API_URL = "http://localhost:8000"
  $env:DOCUMENT_ID = "<job_id / document_id from a completed summarize job>"
  # Must be the SAME account that owns DOCUMENT_ID (ownership is enforced):
  $env:E2E_EMAIL = "you@example.com"
  $env:E2E_PASSWORD = "SecurePass123!"
  cd backend
  python scripts/bench_rag_latency.py
  python scripts/bench_rag_latency.py --csv local_db/rag_latency_bench.csv

Outputs:
  - Console latency breakdown table (mean / p50 / p95 per stage)
  - JSONL rows at backend/local_db/rag_latency_bench.jsonl (or --out)
  - Server logs lines matching: query_latency document_id=... stages_ms=...
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

# Representative mix: factual QA, overview/summarize intent, timeline, short/long,
# keyword-heavy, and a few paraphrases (good for spotting retrieve vs LLM skew).
DEFAULT_QUERIES = [
    "What is the main objective of this document?",
    "Summarize the key findings in 5 bullets.",
    "Give me a brief overview / TL;DR.",
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
    "Timeline of key events in the project.",
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
    "llm_ttft_ms",
    "llm_ttlt_ms",
    "llm_generation_ms",
    "total_ms",
]


def _ok(msg: str) -> None:
    print(f"  PASS  {msg}")


def _fail(msg: str) -> None:
    print(f"  FAIL  {msg}")


def login(session: requests.Session, api: str, email: str, password: str) -> str:
    # Try login first; on failure, register then login
    r = session.post(
        f"{api}/auth/login",
        json={"email": email, "password": password},
        timeout=60,
    )
    if r.status_code != 200:
        session.post(
            f"{api}/auth/register",
            json={"email": email, "password": password, "full_name": "Latency Bench"},
            timeout=60,
        )
        r = session.post(
            f"{api}/auth/login",
            json={"email": email, "password": password},
            timeout=60,
        )
    if r.status_code != 200:
        raise RuntimeError(f"auth failed: {r.status_code} {r.text[:300]}")
    data = r.json()
    token = data.get("access_token") or data.get("token")
    if not token:
        raise RuntimeError(f"no access_token in login response: {data}")
    return token


def run_one(
    session: requests.Session,
    api: str,
    token: str,
    document_id: str,
    query: str,
) -> Dict[str, Any]:
    t0 = time.perf_counter()
    r = session.post(
        f"{api}/rag-query",
        headers={"Authorization": f"Bearer {token}"},
        json={"document_id": document_id, "query": query},
        timeout=300,
    )
    wall_ms = (time.perf_counter() - t0) * 1000.0
    body: Dict[str, Any] = {}
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text[:500]}
    latency = body.get("latency") or {}
    stages = dict(latency.get("stages_ms") or {})
    return {
        "status": r.status_code,
        "query": query,
        "wall_client_ms": round(wall_ms, 3),
        "stages_ms": stages,
        "meta": latency.get("meta") or {},
        "model_used": body.get("model_used"),
        "skill": body.get("skill"),
        "answer_chars": len(body.get("answer") or ""),
        "error": None if r.status_code == 200 else body,
    }


def _pct(xs: List[float], p: float) -> float:
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


def print_table(rows: List[Dict[str, Any]]) -> None:
    ok_rows = [r for r in rows if r["status"] == 200 and r.get("stages_ms")]
    if not ok_rows:
        print("\nNo successful timed rows to aggregate.")
        return

    print("\n=== Latency breakdown (ms) ===")
    header = f"{'stage':28} {'n':>4} {'mean':>10} {'p50':>10} {'p95':>10} {'max':>10}"
    print(header)
    print("-" * len(header))
    for stage in STAGE_ORDER:
        vals = [
            float(r["stages_ms"][stage])
            for r in ok_rows
            if stage in r["stages_ms"]
        ]
        if not vals:
            continue
        print(
            f"{stage:28} {len(vals):4d} {statistics.mean(vals):10.1f} "
            f"{_pct(vals, 50):10.1f} {_pct(vals, 95):10.1f} {max(vals):10.1f}"
        )

    # Share of total
    totals = [float(r["stages_ms"].get("total_ms") or 0) for r in ok_rows]
    llms = [float(r["stages_ms"].get("llm_ttlt_ms") or 0) for r in ok_rows]
    rets = [float(r["stages_ms"].get("retrieval_total_ms") or 0) for r in ok_rows]
    if totals and statistics.mean(totals) > 0:
        m_tot = statistics.mean(totals)
        print(
            f"\nMean share of total: retrieval={100 * statistics.mean(rets) / m_tot:.1f}%  "
            f"llm={100 * statistics.mean(llms) / m_tot:.1f}%"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch RAG latency bench")
    parser.add_argument("--api", default=os.environ.get("API_URL", "http://localhost:8000"))
    parser.add_argument("--document-id", default=os.environ.get("DOCUMENT_ID", ""))
    parser.add_argument("--email", default=os.environ.get("E2E_EMAIL") or f"bench-{uuid.uuid4().hex[:8]}@example.com")
    parser.add_argument("--password", default=os.environ.get("E2E_PASSWORD", "SecurePass123!"))
    parser.add_argument("--limit", type=int, default=int(os.environ.get("BENCH_LIMIT", "25")))
    parser.add_argument(
        "--out",
        default=os.environ.get(
            "BENCH_OUT",
            str(Path(__file__).resolve().parents[1] / "local_db" / "rag_latency_bench.jsonl"),
        ),
    )
    parser.add_argument("--csv", default="", help="Optional CSV path for stages")
    parser.add_argument("--warmup", type=int, default=1, help="Discard first N queries (cold start)")
    args = parser.parse_args()

    api = args.api.rstrip("/")
    document_id = args.document_id.strip()
    if not document_id:
        print("ERROR: set --document-id or DOCUMENT_ID to a completed job/document id")
        return 2

    queries = DEFAULT_QUERIES[: max(1, args.limit)]
    print(f"API={api}")
    print(f"document_id={document_id}")
    print(f"queries={len(queries)} warmup={args.warmup}")

    session = requests.Session()
    try:
        token = login(session, api, args.email, args.password)
        _ok(f"auth as {args.email}")
    except Exception as e:
        _fail(f"auth: {e}")
        return 1

    rows: List[Dict[str, Any]] = []
    for i, q in enumerate(queries):
        is_warmup = i < args.warmup
        label = "warmup" if is_warmup else f"{i - args.warmup + 1}/{len(queries) - args.warmup}"
        print(f"\n[{label}] {q[:80]}")
        try:
            row = run_one(session, api, token, document_id, q)
        except Exception as e:
            row = {
                "status": 0,
                "query": q,
                "wall_client_ms": None,
                "stages_ms": {},
                "meta": {},
                "error": str(e),
            }
        if row["status"] == 200:
            stages = row.get("stages_ms") or {}
            print(
                f"  total={stages.get('total_ms')}  "
                f"retrieve={stages.get('retrieval_total_ms')}  "
                f"llm_ttft={stages.get('llm_ttft_ms')}  "
                f"llm_ttlt={stages.get('llm_ttlt_ms')}  "
                f"model={row.get('model_used')}"
            )
        else:
            _fail(f"HTTP {row['status']}: {row.get('error')}")
        if not is_warmup:
            rows.append(row)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"\nWrote {len(rows)} rows → {out_path}")

    if args.csv:
        csv_path = Path(args.csv)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=["query", "status", "wall_client_ms", "model_used", "skill"]
                + STAGE_ORDER,
            )
            w.writeheader()
            for row in rows:
                rec = {
                    "query": row["query"],
                    "status": row["status"],
                    "wall_client_ms": row.get("wall_client_ms"),
                    "model_used": row.get("model_used"),
                    "skill": row.get("skill"),
                }
                rec.update({k: (row.get("stages_ms") or {}).get(k) for k in STAGE_ORDER})
                w.writerow(rec)
        print(f"Wrote CSV → {csv_path}")

    print_table(rows)
    ok_n = sum(1 for r in rows if r["status"] == 200)
    print(f"\nDone: {ok_n}/{len(rows)} successful")
    return 0 if ok_n == len(rows) and rows else 1


if __name__ == "__main__":
    sys.exit(main())
