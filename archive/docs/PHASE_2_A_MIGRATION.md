# Phase 2.A — ChunkingService (Adaptive Chunk Foundation)

## Summary

Introduced a deterministic **ChunkingService** that builds hierarchy-aware
`AdaptiveChunk`s from triage output. Phase 1 CRE/router scoring unchanged.
Summarize + RAG keep working via duck-typed `.content`.

## Changes

| File | Change |
|------|--------|
| `src/chunking/types.py` | **New** — `AdaptiveChunk`, `ParentNode` |
| `src/chunking/service.py` | **New** — `ChunkingService` / `build_adaptive_chunks` |
| `src/chunking/__init__.py` | **New** — package exports |
| `src/core/config.py` | `USE_ADAPTIVE_CHUNKING`, `CHUNK_MAX_TOKENS`, `CHUNK_SIM_THRESHOLD`, `CHUNK_COLLECTION_NAME`, `chroma_collection()` |
| `src/core/orchestrator.py` | After triage, optional adaptive build; stores `chunk_parents` |
| `src/memory/storage.py` | Chunk columns + migration; Chroma metadata for parent/section/kind |
| `tests/test_chunking.py` | Unit tests |
| `.env.example` | Chunking knobs |

## Public interfaces

### `src.chunking`

| Symbol | Description |
|--------|-------------|
| `AdaptiveChunk` | Chunk with `content`, `parent_id`, `section_path`, `chunk_kind`, `token_estimate` |
| `ParentNode` | Section parent with `child_chunk_indices` |
| `ChunkingService(max_tokens?, sim_threshold?, embed_fn?).build(elements, document_id)` | → `(chunks, parents, meta)` |
| `build_adaptive_chunks(...)` | Convenience wrapper |
| `estimate_tokens(text)` | Approx token count |

### Config

| Env | Default | Meaning |
|-----|---------|---------|
| `USE_ADAPTIVE_CHUNKING` | `true` | Feature flag; `false` → raw triage chunks |
| `CHUNK_MAX_TOKENS` | `512` | Merge budget within a section |
| `CHUNK_SIM_THRESHOLD` | `0.25` | Split when adjacent similarity &lt; threshold |
| `CHUNK_COLLECTION_NAME` | empty | Override Chroma collection; else `CHROMA_COLLECTION_NAME` |

### Storage

SQLite `chunks` gains nullable: `parent_id`, `section_path`, `chunk_kind`, `token_estimate` (auto-migrated via `ALTER TABLE`).

Chroma metadata may include the same keys on upsert.

## Behavior

1. Triage (`unstructured`) still produces layout atoms.
2. If `USE_ADAPTIVE_CHUNKING`:
   - Titles open section parents
   - Tables stay atomic
   - Text/List merge until token budget or similarity drop (NIM embed if available, else lexical overlap)
3. Downstream CRE / summarizers consume `.content` unchanged.

## Acceptance

- [x] Tables remain atomic
- [x] Titles create section parents
- [x] Token budget splits long sections
- [x] Similarity split works with lexical fallback
- [x] `USE_ADAPTIVE_CHUNKING=false` path retained in orchestrator
- [x] Unit tests: `python tests/test_chunking.py`
- [x] Phase 2.0 tests still pass: `python tests/test_job_status.py`
- [ ] Manual E2E summarize + RAG with NIM key

## Rollback

Set `USE_ADAPTIVE_CHUNKING=false`. No need to drop new SQLite columns (nullable).

## Next phase (await approval)

**2.B — Hybrid RetrievalService + Embedding Cache**
