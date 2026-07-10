# Phase 2.F — Understanding Agent (Ingest Cognition)

## Summary

Added the only **ingest-time agent**: structured knowledge extraction over
chunks using the map-tier model chain from `RoutingDecision`, then grounded by
**ValidationService** (not a new agent). Runs **async after summarize completes**
so summarize latency is unchanged. CRE/router scoring untouched.

## Changes

| File | Change |
|------|--------|
| `src/knowledge/schemas.py` | **New** — `KnowledgeDocument`, entities/concepts/events/…, JSON repair |
| `src/knowledge/__init__.py` | **New** |
| `src/validation/service.py` | **New** — `ValidationService.ground_knowledge` (+ QVA facade) |
| `src/validation/__init__.py` | **New** |
| `src/agents/understanding_agent.py` | **New** — extract + `run_understanding_for_document` |
| `src/memory/storage.py` | `knowledge_json` column; `save_knowledge` / `get_knowledge` |
| `src/api/main.py` | Async understand after job complete; `GET /documents/{id}/knowledge` |
| `src/api/schemas.py` | `JobStatus.understanding`; `KnowledgeResponse` |
| `src/core/config.py` / `.env.example` | Understanding flags |
| `tests/test_understanding.py` | Unit tests |

## Public interfaces

### Knowledge

| Symbol | Description |
|--------|-------------|
| `KnowledgeDocument` | entities, concepts, events, topics, citations, relations, meta |
| `extract_json_object(text)` | Parse/repair LLM JSON |
| `EvidenceSpan(chunk_id, quote)` | Required grounding unit |

### Understanding Agent

| Symbol | Description |
|--------|-------------|
| `UnderstandingAgent().extract(document_id, chunks, routing_decision=…)` | → `UnderstandingResult` |
| `run_understanding_for_document(document_id, job_id=…)` | Load → extract → ground → persist |

### ValidationService

| Symbol | Description |
|--------|-------------|
| `ground_knowledge(doc, chunk_texts)` | Drop ungrounded nodes; relations need both endpoints |

### Config

| Env | Default | Meaning |
|-----|---------|---------|
| `ENABLE_UNDERSTANDING` | `true` | Async extract after summarize |
| `UNDERSTANDING_MAX_CHUNKS_PER_CALL` | `6` | Batch size |
| `UNDERSTANDING_MAX_TOKENS` | `2000` | LLM max tokens |

### API

| Endpoint | Behavior |
|----------|----------|
| `GET /job-status/{id}` | Optional `understanding`: `pending\|done\|failed\|skipped` |
| `GET /documents/{id}/knowledge` | Knowledge JSON; 202 if pending; 404 if missing |

### Storage

`documents.knowledge_json` (nullable TEXT, auto-migrated).

## Behavior

1. Summarize graph finishes → job `status=complete` (unchanged latency path).
2. If `ENABLE_UNDERSTANDING`: daemon thread runs Understanding Agent.
3. Batches chunks → map-tier NIM JSON extract → merge → ground → `save_knowledge`.
4. Ungrounded entities/concepts/events/citations dropped; relations without both ends dropped.

## Acceptance

- [x] Every persisted entity has ≥1 evidence `chunk_id` + `quote`
- [x] Ungrounded nodes dropped
- [x] `ENABLE_UNDERSTANDING=false` → zero extraction LLM calls
- [x] Understanding is async post-commit (summarize complete not blocked)
- [x] Unit tests: `python tests/test_understanding.py`
- [x] Prior phase tests still pass
- [ ] Manual E2E: upload → poll understanding → knowledge endpoint non-empty

## Rollback

```
ENABLE_UNDERSTANDING=false
```

No impact on RAG path. Existing `knowledge_json` rows are ignored.

## Next phase (await approval)

**2.G — GraphStore** → **done; see PHASE_2_G_MIGRATION.md**
