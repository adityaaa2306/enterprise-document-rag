# Autonomous Progress Log

## Milestone 0 â€” Session start (2026-07-12)

### State entering session
- Portfolio topology: Render free Web Service + `RUN_EMBEDDED_WORKER=true`
- Deploy commit tip includes entrypoint `wait -n` fix and single-service Blueprint
- Baseline smoke (`SKIP_UPLOAD=1`): health / ready / worker / auth PASS
- Full upload smoke flaky: HTTP 502 while embedded worker processes jobs (free-tier)
- `FinalReport.pdf` present at repo root (untracked)

### Hypothesis for 502s
API and `python -m src.worker` are **two Python processes** â†’ duplicate Torch/Chroma/NIM imports on ~512MB free instances â†’ OOM / unresponsive â†’ Render 502.

### Plan
1. Run embedded worker **in-process** (thread) when `RUN_EMBEDDED_WORKER=true` to share memory
2. Local + production E2E with `FinalReport.pdf`
3. Fix remaining RAG / routing / test failures
4. Document env + deploy checklist

## Milestone 1 — In-process embedded worker (2026-07-12)

### What changed
- RUN_EMBEDDED_WORKER starts durable worker as daemon thread inside API process
- docker-entrypoint-api.sh only runs uvicorn (no second python process)
- Added scripts/e2e_final_report.py for FinalReport.pdf

### Why
Two processes on Render free double RAM -> OOM -> 502 during jobs

### Tests
Unit tests for chroma/phase4/embedded worker

### Remaining
Render deploy + FinalReport E2E local/prod

## Milestone 2 — Embedding input_type + runtime (2026-07-12)

### Changed
- NIM embed_texts passes extra_body input_type (passage/query)
- Retrieval uses input_type=query
- Medium primary = ministral (gemma-4 as fallback)
- JOB_MAX_RUNTIME_SEC default 1800
- In-process embedded worker (prior milestone)

### Why
Asymmetric nemotron-embed returned 400 without input_type; broken dense RAG. Gemma-4 timeouts burned wall-clock past 600s job limit.


## Milestone 3 — FinalReport.pdf E2E PASSED (local + production)

### Local (SQLite + local object store + in-process worker)
- Auth, upload, job complete, summary (6342 chars), RAG (1342), chat PASS
- CRE routed to light tier (CRS=0.265); adaptive chunking 38?14
- Embeddings with input_type working (2048-dim)

### Production (Render + Neon + R2 + in-process worker)
- Commit 7ac1148 live
- Smoke SKIP_UPLOAD: all PASS
- FinalReport.pdf E2E: job 434984a3... complete, summary 7084, RAG 1504, chat PASS
- 104 unit tests passed

### Remaining limitations (accepted)
- Free-tier Render sleeps ~15m; no persistent disk (vectors lost on restart — re-ingest)
- Free NIM: some models timeout; fallbacks handle it
- Separate Background Worker incompatible with embedded Chroma disks
