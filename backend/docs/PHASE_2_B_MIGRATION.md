# Phase 2.B — Hybrid RetrievalService + Embedding Cache

## Summary

Added hybrid retrieval (dense Chroma + BM25 → RRF → NIM rerank → optional
parent expand) behind `ENABLE_HYBRID_RETRIEVAL`, plus a content-addressed
embedding disk cache. Phase 1 CRE/router scoring unchanged. RAG callers still
receive duck-typed `.content` objects via `search_similar_chunks`.

## Changes

| File | Change |
|------|--------|
| `src/memory/embedding_cache.py` | **New** — sha256(model+text) JSON cache under `VECTOR_DB_PATH/embed_cache/` |
| `src/retrieval/bm25.py` | **New** — Okapi BM25 per document; persist under `VECTOR_DB_PATH/bm25/` |
| `src/retrieval/rrf.py` | **New** — Reciprocal Rank Fusion |
| `src/retrieval/service.py` | **New** — `RetrievalService` hybrid pipeline |
| `src/retrieval/__init__.py` | **New** — package exports |
| `src/agents/models.py` | `embed_texts` reads/writes embedding cache when enabled |
| `src/memory/storage.py` | Rebuild BM25 on `store_chunks`; search delegates to RetrievalService; delete BM25 on `delete_chunks` |
| `src/core/config.py` | Hybrid + cache knobs |
| `tests/test_retrieval.py` | Unit tests (RRF, BM25, cache) |
| `.env.example` | New env vars |

## Public interfaces

### `src.retrieval`

| Symbol | Description |
|--------|-------------|
| `RetrievalService().search(query, document_id, top_k?)` | → `RetrievalResult` |
| `RetrievedPassage` | `chunk_id`, `content`, `score`, `parent_id`, `section_path`, `source` |
| `search_as_content_chunks(...)` | Legacy adapter (`.content`) for RAG |
| `reciprocal_rank_fusion(ranked_lists, k=60, top_n?)` | Fuse id rankings |
| `bm25.build_and_save` / `load_index` / `delete_index` | Sparse index I/O |

### Config

| Env | Default | Meaning |
|-----|---------|---------|
| `ENABLE_HYBRID_RETRIEVAL` | `true` | Dense+BM25→RRF→rerank; `false` → dense→rerank only |
| `ENABLE_EMBEDDING_CACHE` | `true` | Disk cache for NIM embeddings |
| `RAG_DENSE_K` | `20` | Dense candidate count |
| `RAG_SPARSE_K` | `20` | BM25 candidate count |
| `RAG_RRF_K` | `20` | Fused candidates before rerank |
| `RAG_RERANK_N` | `20` | Max passages sent to NIM rerank |
| `ENABLE_PARENT_EXPAND` | `true` | Attach sibling/parent-section context |
| `RAG_PARENT_EXPAND_MAX` | `3` | Cap on expanded extras |
| `RAG_TOP_K` | `5` | Final passages (unchanged) |

## Behavior

1. **Ingest** (`store_chunks`): embed (cached) → Chroma + SQLite; rebuild BM25 for `document_id`.
2. **Query** (`search_similar_chunks` → `RetrievalService`):
   - If hybrid on: dense top-`RAG_DENSE_K` + BM25 top-`RAG_SPARSE_K` → RRF → NIM rerank → optional parent expand.
   - If hybrid off: dense → NIM rerank (previous behavior).
   - Missing BM25 index is rebuilt from SQLite on first sparse search.
3. **Cache key**: `sha256(EMBEDDING_MODEL + "\\n" + text)`.

## Acceptance

- [x] RRF unit tests
- [x] BM25 build/search/persist tests
- [x] Embedding cache hit/miss tests
- [x] Config flags present
- [x] `search_similar_chunks` delegates to RetrievalService
- [x] BM25 rebuilt on store; deleted on delete
- [x] Phase 2.0 / 2.A tests still pass
- [ ] Manual E2E RAG with NIM key (hybrid on/off)

## Rollback

```
ENABLE_HYBRID_RETRIEVAL=false
ENABLE_EMBEDDING_CACHE=false
ENABLE_PARENT_EXPAND=false
```

Dense-only path remains. Cache/BM25 files under `VECTOR_DB_PATH` can be deleted safely.

## Next phase (await approval)

**2.C — ContextAssembler** → **done; see PHASE_2_C_MIGRATION.md**
