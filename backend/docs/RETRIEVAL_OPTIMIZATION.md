# Retrieval Optimization Benchmark Report

- Generated (UTC): `20260714T074905Z`
- Document: `31a52f14-687d-47f3-98f1-ed8fee9dd7b6`
- Queries: **25** representative prompts
- Mode: retrieval-only (`RetrievalService.search`) — **no LLM generation / prompt changes**
- Raw: `backend/local_db/perf_investigation/retrieval_bench_20260714T074905Z.jsonl`

## Executive summary

| Metric | Before (investigation) | After | Improvement |
|--------|------------------------|-------|-------------|
| **Retrieval total** | **11,656.9 ms** | **539.5 ms** | **95.4%** |
| BM25 | 1,600.0 ms | **0.1 ms** | 100% |
| Parent expansion | 2,495.0 ms | **0.0 ms** | 100% |
| Chroma dense search | 305.1 ms | **2.8 ms** | 99.1% |
| Query embedding | 892.0 ms | 63.7 ms | 92.9% (cache warm) |
| Reranking | 408.0 ms (404 fail) | **472.7 ms (ok)** | restored |
| RRF / meta | ~0 / unaccounted N+1 | ~0 ms | fixed |

### Success criteria

| Criterion | Target | Result |
|-----------|--------|--------|
| Retrieval total | < 1,000 ms | **PASS (539.5 ms mean, p50 502.6)** |
| BM25 | < 50 ms | **PASS (0.1 ms)** |
| Parent expansion | < 100 ms | **PASS (~0 ms)** |
| Reranker | working or fast bypass | **PASS — `ok` on 25/25** |
| LLM / prompts unchanged | no edits | **PASS** |

---

## Root causes fixed

1. **BM25** — reloaded JSON from disk + full Postgres `retrieve_chunks` every query → **process memory cache + doc_cache text map + posting lists**.
2. **Parent expand / meta** — N+1 Postgres `db.get` per candidate + per-parent queries → **in-memory `doc_cache`**.
3. **Unaccounted ~7s gap** — `_meta_for` + double graph loads outside stage timers → timed + cached.
4. **Graph seed ~1s** — `get_graph` called twice per query over remote Postgres → **single load + process graph cache**.
5. **Rerank 404** — wrong URL `integrate.api.nvidia.com/v1/ranking` → **`ai.api.nvidia.com/v1/retrieval/nvidia/<model>/reranking`** + circuit breaker if all endpoints fail.
6. **Chroma** — collection handle reused in-process.

---

## Stage statistics after (ms)

| Stage | mean | p50 | p95 | max | stdev |
|---|---:|---:|---:|---:|---:|
| `query_embed_ms` | 63.7 | 56.3 | 102.5 | 114.3 | 27.9 |
| `dense_retrieve_ms` | 2.8 | 2.3 | 4.7 | 5.3 | 1.0 |
| `bm25_retrieve_ms` | 0.1 | 0.0 | 0.1 | 0.1 | 0.0 |
| `graph_seed_ms` | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| `rrf_fuse_ms` | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| `meta_lookup_ms` | 0.0 | 0.0 | 0.0 | 0.1 | 0.0 |
| `rerank_ms` | 472.7 | 436.0 | 466.8 | 1278.3 | 168.4 |
| `parent_expand_ms` | 0.0 | 0.0 | 0.1 | 0.1 | 0.0 |
| `retrieval_total_ms` | **539.5** | **502.6** | **559.6** | 1337.0 | 169.2 |

**Dominant remaining cost:** working NIM rerank (~473 ms mean). Local retrieval (BM25 + Chroma + parent + RRF + meta + graph) is **≪ 10 ms** after warmup.

---

## Quality validation

- Rerank status: **`ok` for all 25 queries** (order now comes from real logits, not failed-fallback).
- Hybrid path still returns top-K + parent expand; chunk IDs recorded in JSONL for offline diffs.
- No changes to ResponseAgent, skills, prompts, or chat models in this phase.
- Expected quality effect: **neutral to improved** vs pre-fix (broken rerank previously returned original RRF order after wasting 0.2–1.2s on 404).

---

## Code touchpoints

| Area | Files |
|------|--------|
| Doc chunk cache | `src/retrieval/doc_cache.py` |
| BM25 memory + postings | `src/retrieval/bm25.py` |
| Retrieval service | `src/retrieval/service.py` |
| Rerank URL + circuit | `src/agents/models.py` |
| Graph cache | `src/knowledge/graph_store.py` |
| Config | `ENABLE_RERANK`, `RERANK_HTTP_TIMEOUT_SEC` |
| Bench | `scripts/bench_retrieval_opt.py` |

---

## Next phase (out of scope here)

LLM generation remains ~24s mean and was **not** modified. Optimize generation / streaming / prompt size in a later phase.
