# Phase 2.H — MemoryService + ExplainabilityBuilder + AnswerEnvelope

## Summary

Unified document/conversation/cache access behind **MemoryService**, and attached
**ExplainabilityBuilder** AnswerEnvelope metadata to `/rag-query` (optional fields).
Added **POST /chat** for TTL conversation memory with prior entity resolutions.
CRE/router scoring untouched.

## Changes

| File | Change |
|------|--------|
| `src/memory/service.py` | **New** — MemoryService (embed cache, doc helpers, conversation TTL) |
| `src/explainability/builder.py` | **New** — AnswerEnvelope builder |
| `src/explainability/__init__.py` | **New** |
| `src/api/schemas.py` | Optional envelope fields; `ChatRequest`; `conversation_id` |
| `src/api/main.py` | Envelope on `/rag-query`; new `POST /chat` |
| `src/core/config.py` / `.env.example` | Explainability + conversation TTL |
| `tests/test_memory_explainability.py` | Unit tests |

## Public interfaces

### MemoryService

| Method | Description |
|--------|-------------|
| `embed_cache_*` | Facade over Phase 2.B embedding cache |
| `get_routing` / `get_knowledge` / `get_summary` | Document memory |
| `invalidate_document(id)` | Clear BM25 + graph + conversations after reindex |
| `start_conversation` / `append_turn` / `prior_entity_resolutions` | TTL chat memory |

Conversations stored under `VECTOR_DB_PATH/conversations/{id}.json`.

### ExplainabilityBuilder

Builds `AnswerEnvelope`: `confidence`, `knowledge_sources`, `retrieved_chunks`,
`entities_used`, `reasoning_path`, `missing_context`, `model`, `routing_ref`.

### Config

| Env | Default | Meaning |
|-----|---------|---------|
| `EXPLAINABILITY_ENABLED` | `true` | Attach envelope fields to `/rag-query` |
| `CONVERSATION_TTL_HOURS` | `24` | Conversation expiry |
| `CONVERSATION_MAX_TURNS` | `40` | Cap stored turns |

### API

- `POST /rag-query` — optional `conversation_id`; when explainability on, returns envelope fields
- `POST /chat` — starts/continues conversation; persists entity resolutions for later turns

`EXPLAINABILITY_ENABLED=false` → legacy fields only (`answer`, `sources`, optional `skill`/`model_used`).

## Acceptance

- [x] `/rag-query` includes confidence, retrieved_chunks, reasoning_path, routing_ref when enabled
- [x] Conversation memory returns prior entity resolutions within TTL
- [x] `EXPLAINABILITY_ENABLED=false` → legacy response shape (optional fields null/omitted)
- [x] Unit tests: `python tests/test_memory_explainability.py`
- [x] Prior phase tests still pass
- [ ] Manual E2E two-turn `/chat` with entity carry-over

## Rollback

```
EXPLAINABILITY_ENABLED=false
```

Frontend can ignore unknown JSON fields; optional schema fields keep old clients working.

## Phase 2 status

**2.0 → 2.A → 2.B → 2.C → 2.D → 2.F → 2.G → 2.H complete.**
