# Phase 2.C — ContextAssembler Middleware

## Summary

Added a deterministic **ContextAssembler** between retrieval and generation:
dedupe → sibling merge → token-budget pack → section-ordered `ContextPack` with
provenance. Not an agent. Phase 1 CRE/router scoring unchanged.

## Changes

| File | Change |
|------|--------|
| `src/context/assembler.py` | **New** — `ContextAssembler`, `ContextPack`, provenance |
| `src/context/__init__.py` | **New** — package exports |
| `src/core/config.py` | `USE_CONTEXT_ASSEMBLER`, budgets, dedup threshold |
| `src/api/main.py` | `/rag-query` uses RetrievalService → Assembler when flag on |
| `src/agents/models.py` | `run_large_model_rag` accepts `context_str=` |
| `tests/test_context_assembler.py` | Unit tests |
| `.env.example` | New env vars |

## Public interfaces

### `src.context`

| Symbol | Description |
|--------|-------------|
| `ContextAssembler(...).pack(passages, tier=..., query=...)` | → `ContextPack` |
| `ContextPack` | `context_text`, `passages`, `provenance`, `tokens_used`, `tokens_budget`, `stats`, `source_texts` |
| `PackedPassage` | Packed block with `chunk_ids`, `citation`, section meta |
| `ProvenanceEntry` | `chunk_id` → rank, score, parent, citation |
| `assemble_context(...)` | Convenience wrapper |
| `budget_for_tier(tier)` | Map light/medium/heavy → token budget |

### Config

| Env | Default | Meaning |
|-----|---------|---------|
| `USE_CONTEXT_ASSEMBLER` | `true` | Wire assembler into `/rag-query` |
| `CONTEXT_DEDUP_THRESHOLD` | `0.92` | Near-duplicate lexical collapse |
| `CONTEXT_TOKEN_BUDGET_LIGHT` | `2000` | Budget for light tier (2.D) |
| `CONTEXT_TOKEN_BUDGET_MEDIUM` | `4000` | Budget for medium tier |
| `CONTEXT_TOKEN_BUDGET_HEAVY` | `6000` | Default for `/rag-query` until 2.D |

## Behavior

1. Retrieve passages via `RetrievalService` (hybrid or dense-only).
2. Assembler:
   - Collapse near-duplicates (lexical overlap ≥ threshold; keep higher score)
   - Merge siblings sharing `parent_id`
   - Greedy pack by score under token budget
   - Reorder by `section_path` for LLM text
   - Emit citation markers `[1]`, `[2]`, … + provenance map
3. Generate with `context_str=pack.context_text`; response `sources` = packed passage texts.

When `USE_CONTEXT_ASSEMBLER=false`, previous path (`search_similar_chunks` → join) is used.

## Acceptance

- [x] Near-duplicate chunks collapsed (sim ≥ 0.92)
- [x] Pack respects token budget
- [x] Provenance retains chunk_id + retrieval rank
- [x] `sources` still `List[str]` for `RagQueryResponse`
- [x] Unit tests: `python tests/test_context_assembler.py`
- [x] Prior phase tests still pass
- [ ] Manual E2E RAG with NIM key

## Rollback

```
USE_CONTEXT_ASSEMBLER=false
```

Falls back to raw top-k join via `search_similar_chunks`.

## Next phase (await approval)

**2.D — Response Agent** → **done; see PHASE_2_D_MIGRATION.md**
