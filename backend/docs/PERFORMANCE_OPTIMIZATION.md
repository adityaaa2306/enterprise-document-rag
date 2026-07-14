# Pipeline Performance Optimization Report

## PHASE 1 — Profile Everything ✅

Instrumentation extended in `monitoring/ingestion_latency.py` + `perf/profiler.py`:

| Field | Source |
|-------|--------|
| Start / end offsets | `stage_detail[*].start_offset_ms` / `end_offset_ms` |
| Wall execution time | `stages_ms` + `stage_detail[*].wall_ms` |
| Queue time | per-chunk `queue_ms` (map pool wait) |
| Inference time | per-chunk `call_ms` (NIM) |
| CPU time | `stage_detail[*].cpu_ms` |
| I/O wait proxy | `wall_ms - cpu_ms` |
| Memory / CPU % | `resources_*` via psutil when available |
| Model calls | `map_chunk_stats.model_calls` |
| Average latency | `map_chunk_stats.avg_latency_ms` |
| Waterfall | `meta.waterfall` ASCII bars |
| Ranked bottlenecks | `meta.bottleneck_rank` |

Artifacts written per job: `{VECTOR_DB_PATH}/ingest_latency/{job_id}.json`

Typical pre-optimization shape (large PDF, MAP_MAX_WORKERS=3):

```
Upload / queue          █
Parsing / triage        ████
Capability / plan       █
CRE + routing           █
Chunk summaries (map)   ████████████████████████████  ← dominant
Validation              ██
Escalate                ████████
Compile                 ████████████
Store / embed           █████
Metrics / carbon        ██
```

## PHASE 2 — Ranked Bottlenecks ✅

| Rank | Operation | Why slow | Fix applied |
|------|-----------|----------|-------------|
| 1 | Map summarize (sequential waves of 3) | NIM-bound, low concurrency | `MAP_MAX_WORKERS=8` |
| 2 | Hierarchical compile batches sequential | Independent batches waited | `COMPILE_MAX_WORKERS=4` parallel |
| 3 | Store embed after compile | Embed waited for compile | Prefetch during map |
| 4 | Duplicate QVA after escalate | Full validate twice per cycle | Validate only in `validate_map`; incremental reuse |
| 5 | Per-chunk Chroma upserts | N round-trips | Bulk upsert batches of 64 |
| 6 | Semantic merge pair embeds | O(sections) HTTP | Batch embed all pairs per pass |
| 7 | Progress DB writes every chunk | Sync upsert spam | Throttle `PROGRESS_WRITE_INTERVAL_SEC` |
| 8 | Electricity Maps HTTP each job | Blocking network | TTL cache 300s |
| 9 | Frontend 3s poll | Stale UI | 1s poll + SSE `/job-events` |
| 10 | Token recount | Repeated `len//4` | Content-hash token cache |

## Phases 3–16 — Implementation checklist

| Phase | Status | What shipped |
|-------|--------|--------------|
| 3 Parallelize | ✅ | Map 8 workers, validate workers, compile batch pool, bulk chroma |
| 4 Streaming pipeline | ✅ | Embed prefetch overlaps map→compile; progress streams live |
| 5 Remove duplicates | ✅ | Escalate no longer re-validates; incremental QVA; token/grid caches |
| 6 Model call opt | ✅ | Same calls, higher concurrency + connection reuse (existing client) |
| 7 Validation opt | ✅ | Parallel QVA; incremental revalidate failed only; no blocking of good chunks |
| 8 Compile opt | ✅ | Parallel intermediate batches; hierarchy still starts at compile node |
| 9 Cache | ✅ | Tokens, Electricity Maps TTL, embeddings (existing), carbon constants helpers |
| 10 Async | ✅ | Throttled progress; SSE async generator; prefetch thread pool |
| 11 GPU util | ✅ | Overlap prompt/inference via larger map pool; embed prefetch vs CPU stages |
| 12 DB | ✅ | Throttled progress; milestone force-flush; bulk chroma |
| 13 Frontend | ✅ | 1s poll, stage/chunk progress bar, SSE endpoint |
| 14 Carbon | ✅ | Equations untouched; only grid fetch cached |
| 15 Quality | ✅ | Tests for incremental QVA equivalence + existing suites |
| 16 Benchmarks | ✅ | `scripts/bench_perf_primitives.py` + ingest_latency JSON |

## Functional equivalence guarantees

- Routing / CRE / strategy selection: unchanged
- QVA thresholds: unchanged
- Carbon accounting formulas: unchanged
- Escalation still re-summarizes failed chunks only
- Validation still required (never skipped)
- Compile still medium-first then heavy on QVA fail

## How to verify end-to-end

```bash
cd backend
python -m pytest tests/test_perf_optimizations.py tests/test_quality_validation.py -q
python -m scripts.bench_perf_primitives
# Then run a real summarize job and inspect:
#   local_db/aux/ingest_latency/<job_id>.json
# Compare stages_ms + meta.waterfall before/after worker restart with new settings.
```
