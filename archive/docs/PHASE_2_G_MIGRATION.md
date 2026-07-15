# Phase 2.G — GraphStore + Graph-Seeded Retrieval

## Summary

Persisted document knowledge graphs from Understanding output, and optionally
seed hybrid retrieval with entity-neighborhood chunk ids when the query
mentions known entities. Not an agent. CRE/router untouched.

## Changes

| File | Change |
|------|--------|
| `src/knowledge/graph_store.py` | **New** — `GraphStore`, nodes/edges tables, neighbor lookup |
| `src/knowledge/__init__.py` | Export graph helpers |
| `src/agents/understanding_agent.py` | Sync graph after knowledge save |
| `src/retrieval/service.py` | Optional graph seed as third RRF list; debug `seed_ids` |
| `src/api/main.py` | `GET /documents/{id}/graph` |
| `src/api/schemas.py` | `GraphResponse` |
| `src/core/config.py` / `.env.example` | Graph seed flags |
| `tests/test_graph_store.py` | Unit tests |

## Public interfaces

### `src.knowledge.graph_store`

| Symbol | Description |
|--------|-------------|
| `GraphStore().replace_from_knowledge(doc)` | Idempotent replace nodes/edges |
| `GraphStore().upsert_edge(...)` | Merge evidence; keep max confidence |
| `GraphStore().get_graph(document_id)` | → `DocumentGraph` |
| `GraphStore().match_entity_ids(doc, query)` | Name/alias substring match |
| `GraphStore().neighbor_chunk_ids(doc, query)` | Seed chunk ids (1-hop, conf≥τ) |
| `sync_graph_from_knowledge(document_id, knowledge?)` | Write-path helper |

### Config

| Env | Default | Meaning |
|-----|---------|---------|
| `ENABLE_GRAPH_SEED` | `true` | Inject graph seeds into retrieval RRF |
| `GRAPH_SEED_MAX_CHUNKS` | `8` | Cap seed chunk ids |
| `GRAPH_SEED_MIN_CONFIDENCE` | `0.4` | Min edge confidence for 1-hop expand |

### API

`GET /documents/{id}/graph` → `{ document_id, nodes[], edges[] }`  
Lazy-syncs from `knowledge_json` if tables empty.

### Retrieval

When `ENABLE_GRAPH_SEED=true` and entities match the query:
`RRF([dense, sparse, seed_ids])`. Debug includes `seed_ids` / `graph_seed`.
When `false`, behavior matches Phase 2.B hybrid (two-list RRF).

## Acceptance

- [x] Graph endpoint returns nodes/edges for understood docs
- [x] Neighbor seed returns entity + 1-hop evidence chunk ids
- [x] `ENABLE_GRAPH_SEED=false` → no seed list (2.B-equivalent fusion inputs)
- [x] Edge upsert idempotent (merge evidence, max confidence)
- [x] Unit tests: `python tests/test_graph_store.py`
- [x] Prior phase tests still pass
- [ ] Manual E2E: understand → graph endpoint → entity RAG shows `seed_ids` in logs

## Rollback

```
ENABLE_GRAPH_SEED=false
```

Graph remains available as read-only export via `/graph`.

## Next phase (await approval)

**2.H — Memory + Explainability** → **done; see PHASE_2_H_MIGRATION.md**
