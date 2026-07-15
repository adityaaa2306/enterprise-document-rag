# Phase 2.0 — Pipeline Stabilization

## Summary

Fixed job-result readiness and documented the canonical `document_id == job_id`
convention for RAG. Phase 1 CRE / router / feature scoring were not modified.

## Problem

1. `finalize_metrics` set `JOB_STATUSES[status] = "completed"` while
   `GET /job-result/{job_id}` required `"complete"`.
2. Triage stamped `Chunk.document_id` from the upload filename, which could
   diverge from the API `document_id` (job UUID) used for Chroma/SQLite.

## Changes

| File | Change |
|------|--------|
| `src/core/job_status.py` | **New** — status normalization + readiness helpers |
| `src/memory/document_ids.py` | **New** — `align_chunks_to_document_id` |
| `src/core/orchestrator.py` | Finalize leaves status as `processing`; API owns terminal `complete` |
| `src/api/main.py` | Uses canonical status constants; `/job-result` uses `is_job_ready_for_result` |
| `src/memory/storage.py` | Align chunks at store time; docs for convention |
| `tests/test_job_status.py` | Unit + regression tests |
| `docs/PHASE_2_0_MIGRATION.md` | This document |

## Public interfaces

### `src.core.job_status`

| Symbol | Type | Description |
|--------|------|-------------|
| `STATUS_PROCESSING` | `str` | `"processing"` |
| `STATUS_COMPLETE` | `str` | `"complete"` (canonical success) |
| `STATUS_ERROR` | `str` | `"error"` |
| `normalize_job_status(raw)` | `(str\|None) -> str` | Maps aliases (`completed`, `done`, …) → canonical |
| `is_job_complete(raw)` | `(str\|None) -> bool` | Success including aliases |
| `is_job_ready_for_result(status_dict)` | `(dict\|None) -> bool` | Complete **and** `result` payload present |

### Storage

| Symbol | Description |
|--------|-------------|
| `src.memory.document_ids.align_chunks_to_document_id` | Returns chunks with `document_id` set to the canonical job UUID |
| `store_document_data(job_id, ...)` | Indexes under `document_id = job_id` |

### API contract (unchanged paths)

- `POST /summarize` → `{ job_id, document_id }` with **`document_id === job_id`**
- `GET /job-status/{job_id}` → progress; terminal success status is **`complete`**
- `GET /job-result/{job_id}` → available iff status normalizes to `complete` **and** `result` exists
- `POST /rag-query` → use **`document_id` from summarize/job-result** (the job UUID)

## Acceptance

- [x] Status helper unit tests
- [x] `/job-result` gate requires complete + result
- [x] Chunks aligned to job_id at store time
- [x] CRE/router regression still passes (`python tests/test_job_status.py`)
- [ ] Full E2E upload with live NIM key (manual; requires `NVIDIA_API_KEY`)

## Rollback

Revert the files listed above. No DB migrations.

## Next phase (do not start without approval)

**2.A — ChunkingService**
