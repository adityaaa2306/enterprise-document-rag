# Phase 2.D — Response Agent (Query Cognition)

## Summary

Introduced the only **query-time agent**: intent → skill registry → routed NIM
model chain over a `ContextPack`. Persists Phase-1 `RoutingDecision` on the
document for query-time reuse. CRE / intelligent_router scoring untouched.

## Changes

| File | Change |
|------|--------|
| `src/agents/response_agent.py` | **New** — `ResponseAgent`, intent classify, model chain resolve |
| `src/agents/skills/registry.py` | **New** — skill registry |
| `src/agents/skills/qa.py` | **New** — grounded QA skill |
| `src/agents/skills/summarize_excerpt.py` | **New** — summarize skill |
| `src/agents/skills/timeline.py` | **New** — basic timeline skill |
| `src/memory/storage.py` | `documents.routing_json` + `get_routing_decision` |
| `src/core/orchestrator.py` | Persist `routing_decision` on store/finalize |
| `src/api/main.py` | `/rag-query` → Response Agent when enabled |
| `src/api/schemas.py` | Optional `skill`, `model_used` on `RagQueryResponse` |
| `src/core/config.py` / `.env.example` | Response Agent flags |
| `tests/test_response_agent.py` | Unit tests |

## Public interfaces

### `src.agents.response_agent`

| Symbol | Description |
|--------|-------------|
| `ResponseAgent().answer(query, pack=..., document_id=..., routing_decision=...)` | → `ResponseResult` |
| `classify_intent(query)` | → `qa` / `summarize_excerpt` / `timeline` |
| `resolve_model_chain(routing_decision?)` | Prefer `compile_fallbacks`, else heavy list |

### Skills

| Skill | Trigger (rules) |
|-------|-----------------|
| `qa` | Default / unknown |
| `summarize_excerpt` | summarize, summary, overview, tldr, … |
| `timeline` | timeline, chronology, when did, … |

### Config

| Env | Default | Meaning |
|-----|---------|---------|
| `USE_RESPONSE_AGENT` | `true` | Use Response Agent on `/rag-query` |
| `RESPONSE_DEFAULT_SKILL` | `qa` | Fallback skill |
| `RESPONSE_USE_ROUTING_DECISION` | `true` | Prefer stored compile chain |

### Storage

`documents.routing_json` (nullable TEXT, auto-migrated) stores the Phase-1
`RoutingDecision` dict from summarize.

### API

`RagQueryResponse` gains optional `skill` and `model_used` (backward compatible).

## Behavior

1. Summarize job stores `routing_decision` with the document.
2. `/rag-query`: retrieve → ContextAssembler (tier from routing) → Response Agent.
3. Agent: classify intent → skill prompt from `ContextPack` → `call_chat_with_fallback(compile_fallbacks + heavy safety net)`.
4. Logs: `ResponseAgent: skill=… model_used=…`.

## Acceptance

- [x] `/rag-query` uses Response Agent (`skill` / `model_used` in response + logs)
- [x] Stored `compile_fallbacks` tried before blind heavy-only list
- [x] Unknown intent defaults to `qa`
- [x] Phase-1 map/escalate path untouched (no CRE/router formula edits)
- [x] Unit tests: `python tests/test_response_agent.py`
- [x] Prior phase tests still pass
- [ ] Manual E2E summarize → rag-query; assert `model_used` ∈ expected chain

## Rollback

```
USE_RESPONSE_AGENT=false
```

Falls back to `run_large_model_rag` (still uses ContextAssembler if enabled).

## Next phase (await approval)

**2.F — Understanding Agent** → **done; see PHASE_2_F_MIGRATION.md**
