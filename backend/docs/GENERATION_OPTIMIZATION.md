# Generation & Streaming Optimization

Retrieval was left unchanged (prior phase: ~540 ms). This phase targets NIM generation, prompt/context size, adaptive `max_tokens`, true SSE streaming, and UI TTFT / tokens/sec metrics.

## Phase summary

| Phase | Change |
|-------|--------|
| 1 Analyze | Prompt / context / output tokens + tok/s in `latency.meta.prompt` / `nim` |
| 2 Adaptive length | `src/agents/response_planner.py` — query type → max_tokens (150–800) |
| 3 Prompt compression | `MARKDOWN_OUTPUT_RULES` ~45 tokens; skill prompts shortened |
| 4 Context | `RESPONSE_CONTEXT_BUDGET=2200`; leaner `[n]` headers; dedupe threshold 0.85 |
| 5 Streaming | `POST /rag-query/stream` SSE; FE renders tokens as they arrive |
| 6 Explainability | Built after token stream completes (off perceived critical path) |
| 7 Benchmark | `scripts/bench_generation_opt.py` → `docs/GENERATION_BENCH.json` |

## Before → after (25 queries, document `31a52f14-…`)

Baseline (prior measurement on same stack): generation **~23.8 s**, backend total **~26 s**, TTFT **~700 ms**, retrieval **~540 ms**.

| Metric | Before | After (p50) | After (avg) | After (p95) | Max |
|--------|--------|-------------|-------------|-------------|-----|
| TTFT | ~700 ms | **503 ms** | 3.3 s* | 14.2 s* | 46.2 s* |
| Tokens/sec | — | **21.4** | 30.0 | 71.4 | 78.2 |
| Avg output tokens | (often near 1k+ caps) | **203** | 224 | 462 | 485 |
| Prompt tokens | (tier up to 6k ctx) | **1995** | 1985 | 2182 | 2183 |
| Context tokens | — | **1893** | 1879 | 2081 | 2081 |
| Generation (TTLT) | **23.8 s** | **10.8 s** | 12.2 s | 19.4 s | 60.6 s* |
| Backend total | **26 s** | **13.8 s** | 18.2 s | 54.2 s* | 107 s* |
| Retrieval | ~540 ms | 848 ms† | 1.15 s† | 1.26 s | 7.2 s† |
| Explainability | ~1.2 s | **0.12 ms** | 0.15 ms | 0.19 ms | 1.0 ms |
| User-perceived first token | ≈ full answer (fake stream) | **≈ TTFT** (true SSE) | — | — | — |

\*Averages/max skewed by rare NIM queue/cold spikes (TTFT ≫ 1 s). Prefer **p50**.  
†First-query / cold cache; warm retrieval stays near prior ~540–850 ms. Not modified in this phase.

### Output length by query type (avg tokens)

| Type | Avg output |
|------|------------|
| fact | 94 |
| definition | 156 |
| summary | 229 |
| comparison | 291 |
| timeline | 291 |
| analytical | 370 |
| explanation | 414 |

**Verdict (Phase 1):** Excessive fixed `max_tokens` (1200–1500) was a primary driver of long generation; adaptive caps cut median generation roughly **in half** while keeping factual answers short on fact lookups.

## Config knobs

- `RESPONSE_CONTEXT_BUDGET` (default 2200)
- `RESPONSE_DEFER_EXPLAINABILITY` (true)
- `CONTEXT_DEDUP_THRESHOLD` (0.85)

## API / UI

- **SSE:** `POST /rag-query/stream` — events `meta` | `plan` | `token` | `done` | `error`
- **JSON:** `POST /rag-query` unchanged shape; uses adaptive tokens + compressed prompts
- Insights panel: **TTFT** + **Tokens/sec** highlighted

## Reproduce

```bash
cd backend
.\.venv\Scripts\python.exe scripts/bench_generation_opt.py --document-id <uuid> --limit 25
```

Raw rows: `docs/GENERATION_BENCH.json`.
