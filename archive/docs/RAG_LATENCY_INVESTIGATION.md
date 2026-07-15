# RAG Query Latency Investigation Report

- Generated (UTC): `20260714T073911Z`
- Mode: in-process `_run_rag_query` (measured stages; no auth overhead)
- Document ID: `31a52f14-687d-47f3-98f1-ed8fee9dd7b6`
- Queries run: 5 (successful timed: 5)
- Raw data: `D:/green-agentic-rag-main/backend/local_db/perf_investigation/live_queries_20260714T073911Z.jsonl`

## Executive summary (evidence)

| Metric | Measured mean | Max |
|--------|---------------|-----|
| End-to-end query | **38.6 s** | **47.2 s** |
| NIM TTLT (generation) | **23.8 s (61.8%)** | 34.1 s |
| Retrieval total | **11.7 s (30.2%)** | 16.9 s |
| Parent expand alone | **2.5 s (6.5%)** | 3.5 s |
| BM25 | **1.6 s (4.1%)** | 2.4 s |
| Explainability | **1.2 s (3.0%)** | 1.5 s |
| Query embed | **0.9 s (2.3%)** | 2.4 s |
| NIM TTFT / first byte | **~0.7 s** | ~1.1 s |
| Retries / fallbacks | **0** on all 5 queries | — |
| Ingest ops on query path | **none** (`pipeline_validation.clean=true`) | — |

**Why UI can feel ~60s:** these in-process runs average ~39s. Adding browser RTT, React reveal animation, and occasional colder NIM / larger prompts can push perceived wait toward ~60s. The dominant measured cost is **NVIDIA chat TTLT**, not document re-ingestion.

**Additional measured finding:** every query logged `Rerank failed: 404 ... /v1/ranking` then fell back. `rerank_ms` still burns ~0.2–1.2s on the failed HTTP call.

**No optimizations were applied** in this investigation.

## Method

Stage timings are measured with `time.perf_counter()` inside retrieval, context assembly, NIM stream-measure (TTFT/TTLT), explainability, and returned in `latency.stages_ms`. Values below are **not estimates**.

## Stage table (mean / max)

| Stage | n | mean ms | max ms | mean % of total |
|---|---:|---:|---:|---:|
| `query_embed_ms` | 5 | 892.0 | 2410.7 | 2.3% |
| `dense_retrieve_ms` | 5 | 305.1 | 1514.6 | 0.8% |
| `bm25_retrieve_ms` | 5 | 1600.0 | 2396.5 | 4.1% |
| `rrf_fuse_ms` | 5 | 0.0 | 0.0 | 0.0% |
| `rerank_ms` | 5 | 408.0 | 1226.5 | 1.1% |
| `parent_expand_ms` | 5 | 2495.0 | 3510.2 | 6.5% |
| `retrieval_total_ms` | 5 | 11656.9 | 16891.6 | 30.2% |
| `context_assemble_ms` | 5 | 4.4 | 7.1 | 0.0% |
| `nim_network_ms` | 5 | 725.6 | 1050.0 | 1.9% |
| `llm_ttft_ms` | 5 | 725.7 | 1050.1 | 1.9% |
| `llm_ttlt_ms` | 5 | 23832.6 | 34087.9 | 61.8% |
| `llm_generation_ms` | 5 | 23832.6 | 34087.9 | 61.8% |
| `postprocess_ms` | 5 | 0.0 | 0.0 | 0.0% |
| `explainability_ms` | 5 | 1161.7 | 1492.5 | 3.0% |
| `citations_ms` | 5 | 0.0 | 0.0 | 0.0% |
| `total_ms` | 5 | 38572.5 | 47190.6 | — |

## Client vs backend (in-process wall ≈ backend)

- Mean call wall: **38612.3 ms** (38.61 s)
- Mean backend total: **38572.5 ms** (38.57 s)

## Per-query detail

### Query 1: What is the main objective of this document?

- Model: `mistralai/ministral-14b-instruct-2512` · skill `qa`
- Wall: 34375.8 ms
- Pipeline clean: **True** violations=[]
- NIM measured: first_byte=805.499 ttft=805.637 ttlt=11368.509 inference=10563.01 retries=0 fallback=False http=200
- Tokens: system=31 query=11 context=3826 final=4127 output=524
- Embedding: model=nvidia/llama-nemotron-embed-1b-v2 hits=0 misses=1 api_ms=2339.272 dim=2048

```
query_embed_ms                   2410.7 ms
dense_retrieve_ms                1514.6 ms
bm25_retrieve_ms                 1100.0 ms
rrf_fuse_ms                         0.0 ms
rerank_ms                        1226.5 ms
parent_expand_ms                 3510.2 ms
retrieval_total_ms              16891.6 ms
context_assemble_ms                 7.1 ms
nim_network_ms                    805.5 ms
llm_ttft_ms                       805.6 ms
llm_ttlt_ms                     11368.5 ms
llm_generation_ms               11368.5 ms
postprocess_ms                      0.0 ms
explainability_ms                1492.5 ms
citations_ms                        0.0 ms
total_ms                        34222.6 ms
```

### Query 2: Summarize the key findings in 5 bullets.

- Model: `mistralai/ministral-14b-instruct-2512` · skill `summarize_excerpt`
- Wall: 42984.5 ms
- Pipeline clean: **True** violations=[]
- NIM measured: first_byte=990.407 ttft=990.498 ttlt=29130.336 inference=28139.929 retries=0 fallback=False http=200
- Tokens: system=34 query=10 context=3412 final=3699 output=341
- Embedding: model=nvidia/llama-nemotron-embed-1b-v2 hits=0 misses=1 api_ms=320.114 dim=2048

```
query_embed_ms                    364.8 ms
dense_retrieve_ms                   2.4 ms
bm25_retrieve_ms                 2396.5 ms
rrf_fuse_ms                         0.0 ms
rerank_ms                         192.3 ms
parent_expand_ms                 2963.3 ms
retrieval_total_ms              11459.7 ms
context_assemble_ms                 4.1 ms
nim_network_ms                    990.4 ms
llm_ttft_ms                       990.5 ms
llm_ttlt_ms                     29130.3 ms
llm_generation_ms               29130.3 ms
postprocess_ms                      0.0 ms
explainability_ms                1106.4 ms
citations_ms                        0.0 ms
total_ms                        42973.9 ms
```

### Query 3: What are the limitations or risks mentioned?

- Model: `mistralai/ministral-14b-instruct-2512` · skill `qa`
- Wall: 47202.3 ms
- Pipeline clean: **True** violations=[]
- NIM measured: first_byte=1049.963 ttft=1050.097 ttlt=34087.853 inference=33037.89 retries=0 fallback=False http=200
- Tokens: system=31 query=11 context=3978 final=4279 output=535
- Embedding: model=nvidia/llama-nemotron-embed-1b-v2 hits=0 misses=1 api_ms=350.643 dim=2048

```
query_embed_ms                    724.5 ms
dense_retrieve_ms                   2.8 ms
bm25_retrieve_ms                 1699.3 ms
rrf_fuse_ms                         0.0 ms
rerank_ms                         209.1 ms
parent_expand_ms                 2134.3 ms
retrieval_total_ms              10752.2 ms
context_assemble_ms                 3.3 ms
nim_network_ms                   1050.0 ms
llm_ttft_ms                      1050.1 ms
llm_ttlt_ms                     34087.9 ms
llm_generation_ms               34087.9 ms
postprocess_ms                      0.0 ms
explainability_ms                1068.3 ms
citations_ms                        0.0 ms
total_ms                        47190.6 ms
```

### Query 4: Extract any numerical results or percentages.

- Model: `mistralai/ministral-14b-instruct-2512` · skill `qa`
- Wall: 25527.3 ms
- Pipeline clean: **True** violations=[]
- NIM measured: first_byte=425.177 ttft=425.347 ttlt=12744.287 inference=12319.11 retries=0 fallback=False http=200
- Tokens: system=31 query=11 context=3853 final=4153 output=673
- Embedding: model=nvidia/llama-nemotron-embed-1b-v2 hits=0 misses=1 api_ms=234.999 dim=2048

```
query_embed_ms                    561.9 ms
dense_retrieve_ms                   3.1 ms
bm25_retrieve_ms                 1515.9 ms
rrf_fuse_ms                         0.0 ms
rerank_ms                         214.7 ms
parent_expand_ms                 2137.9 ms
retrieval_total_ms              10198.9 ms
context_assemble_ms                 4.5 ms
nim_network_ms                    425.2 ms
llm_ttft_ms                       425.3 ms
llm_ttlt_ms                     12744.3 ms
llm_generation_ms               12744.3 ms
postprocess_ms                      0.0 ms
explainability_ms                1069.3 ms
citations_ms                        0.0 ms
total_ms                        25514.8 ms
```

### Query 5: Explain this like I'm a beginner.

- Model: `mistralai/ministral-14b-instruct-2512` · skill `qa`
- Wall: 42971.4 ms
- Pipeline clean: **True** violations=[]
- NIM measured: first_byte=356.958 ttft=357.086 ttlt=31832.161 inference=31475.203 retries=0 fallback=False http=200
- Tokens: system=31 query=8 context=3978 final=4276 output=544
- Embedding: model=nvidia/llama-nemotron-embed-1b-v2 hits=0 misses=1 api_ms=353.597 dim=2048

```
query_embed_ms                    398.2 ms
dense_retrieve_ms                   2.5 ms
bm25_retrieve_ms                 1288.5 ms
rrf_fuse_ms                         0.0 ms
rerank_ms                         197.6 ms
parent_expand_ms                 1729.1 ms
retrieval_total_ms               8982.1 ms
context_assemble_ms                 2.8 ms
nim_network_ms                    357.0 ms
llm_ttft_ms                       357.1 ms
llm_ttlt_ms                     31832.2 ms
llm_generation_ms               31832.2 ms
postprocess_ms                      0.0 ms
explainability_ms                1071.9 ms
citations_ms                        0.0 ms
total_ms                        42960.6 ms
```

## Top 5 bottlenecks

1. **`llm_ttlt_ms`** — 23832.6 ms mean (61.8% of backend total)
2. **`parent_expand_ms`** — 2495.0 ms mean (6.5% of backend total)
3. **`bm25_retrieve_ms`** — 1600.0 ms mean (4.1% of backend total)
4. **`explainability_ms`** — 1161.7 ms mean (3.0% of backend total)
5. **`query_embed_ms`** — 892.0 ms mean (2.3% of backend total)

## Root cause analysis

### `llm_ttlt_ms` (61.8%)

- Category: **NVIDIA API / inference**
- Analysis: Chat completion wall time on NVIDIA NIM. TTFT/TTLT measured via streaming instrumentation; response is fully accumulated before return.
- Confidence: **high**

### `parent_expand_ms` (6.5%)

- Category: **Retrieval (local)**
- Analysis: Local Chroma/BM25/RRF/parent-expand work.
- Confidence: **high**

### `bm25_retrieve_ms` (4.1%)

- Category: **Retrieval (local)**
- Analysis: Local Chroma/BM25/RRF/parent-expand work.
- Confidence: **high**

### `explainability_ms` (3.0%)

- Category: **Backend local**
- Analysis: Local CPU stage (assemble / explainability / post-process).
- Confidence: **medium-high**

### `query_embed_ms` (2.3%)

- Category: **NVIDIA API / embedding**
- Analysis: Query embedding NIM call; cache hits reduce embed_api_ms to ~0.
- Confidence: **high**

## Phase 3 — ingest ops during query

- All queries clean: **True**
- Guards active on `store_chunks` and BM25 rebuild; violations would appear in `pipeline_validation.ingest_ops_on_query_path`.

## Non-goals

- No optimizations, caching changes, or retrieval redesign were performed.
