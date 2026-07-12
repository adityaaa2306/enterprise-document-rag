# Autonomous Progress Log

## Milestone 0 — Session start (2026-07-12)

### State entering session
- Portfolio topology: Render free Web Service + `RUN_EMBEDDED_WORKER=true`
- Deploy commit tip includes entrypoint `wait -n` fix and single-service Blueprint
- Baseline smoke (`SKIP_UPLOAD=1`): health / ready / worker / auth PASS
- Full upload smoke flaky: HTTP 502 while embedded worker processes jobs (free-tier)
- `FinalReport.pdf` present at repo root (untracked)

### Hypothesis for 502s
API and `python -m src.worker` are **two Python processes** → duplicate Torch/Chroma/NIM imports on ~512MB free instances → OOM / unresponsive → Render 502.

### Plan
1. Run embedded worker **in-process** (thread) when `RUN_EMBEDDED_WORKER=true` to share memory
2. Local + production E2E with `FinalReport.pdf`
3. Fix remaining RAG / routing / test failures
4. Document env + deploy checklist

## Milestone 1 � In-process embedded worker (2026-07-12)

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
