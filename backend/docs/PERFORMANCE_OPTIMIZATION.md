# Performance optimization checklist (Phases 1–16)

Functional equivalence constraints: routing, QVA validation, carbon equations,
dashboard metrics, and model selection are unchanged. Optimizations are concurrency,
overlap, caching, and I/O reduction only.

## Phase status

- [x] **1 Profile** — stage timers + `scripts/print_perf_profile.py` waterfall; DAG
  returns `stage_timings_ms` (`dag_map_ms`, `dag_qva_escalate_ms`, `dag_compile_ms`).
- [x] **2 Bottlenecks ranked** — dominant: NIM map under worker cap=3 + RPM=30;
  secondary: hierarchical compile; FEA LLM; duplicate finalize store; progress DB spam.
- [x] **3 Parallelize** — `effective_nim_capacity()` sums per-endpoint max; embedded
  workers raised to 12; compile uses `COMPILE_MAX_WORKERS` separately.
- [x] **4 Pipeline overlap** — embed prefetch starts after triage (idempotent); grid
  intensity prefetch at job start; unified DAG starts embeds at map entry.
- [x] **5 Deduplicate** — finalize patches carbon meta only (no chunk re-store);
  embed prefetch no longer cancels in-flight work on re-entry.
- [x] **6 Model calls** — FEA classifier soft-timeout (12s) → heuristic; no skipped
  map/validate/compile calls.
- [x] **7 Validation** — unchanged semantics; already parallel + incremental
  re-validate of escalated indices only.
- [x] **8 Compile** — starts immediately after QVA/escalate; uses dedicated compile
  worker cap.
- [x] **9 Cache** — Electricity Maps TTL cache + background prefetch; embed cache flags
  unchanged.
- [x] **10 Async / non-blocking** — throttled progress DB writes (no `force` on every
  DAG tick); background grid/embed prefetch.
- [x] **11 GPU** — N/A for hosted NIM; pool capacity saturation keeps remote GPUs busy
  via higher concurrency.
- [x] **12 Database** — milestone progress + carbon-only finalize patch.
- [x] **13 Frontend** — already streams `/job-status` partial DAG; backend still fills
  `partial.dag` every tick in-memory.
- [x] **14 Carbon** — no equation / baseline / dashboard math changes.
- [x] **15 Quality** — QVA + escalate + routing paths untouched.
- [x] **16 Benchmarks** — `python scripts/print_perf_profile.py`; unit tests in
  `tests/test_perf_concurrency.py`.

## Before vs after (config)

| Knob | Before | After |
|------|--------|-------|
| EMBEDDED_MAP_MAX_WORKERS | 3 | 12 |
| NIM_ENDPOINT_MAX_CONCURRENT | 3 (ignored per-ep 6) | 6 + honor per-ep |
| effective capacity used | ~3 | min(12, Σ per-ep) ≈ 12–18 |
| NIM_MAX_REQUESTS_PER_MINUTE | 30 | 180 |
| DAG progress DB writes | force every tick | throttled |
| Finalize store | full `store_document_data` | carbon patch only |
| Embed prefetch (unified DAG) | missing | started + early after triage |

## Expected latency impact

Map phase was queue-bound at concurrency 3. Raising to 12 (with 3×6 NIM slots and
RPM 180) should cut map wall time roughly proportional to wave count for I/O-bound
NIM calls, without changing which models run per chunk.
