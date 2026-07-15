# Smart Routing UX Migration

## Summary

The primary UX no longer asks users to pick **Eco / Balanced / Max Quality**.
Default path is **Upload → Process document** with **Smart Routing** (`mode=automatic`).
Optional Advanced Settings only nudge Intelligent Router utility weights; CRE floors are unchanged.

## Preference mapping

| UI / client sends | Backend `MODE_WEIGHTS` key | Notes |
|-------------------|----------------------------|--------|
| `automatic` (default) | `automatic` (= balanced weights) | Recommended |
| `fastest` | `fastest` | ↑ latency / availability |
| `lowest_cost` | `lowest_cost` | ↑ cost weight |
| `lowest_carbon` | `lowest_carbon` | same weights as legacy `eco` |
| `highest_quality` | `highest_quality` | same as legacy `performance` / `quality` |
| Legacy `eco` | `eco` | still accepted |
| Legacy `balanced` | `balanced` | still accepted |
| Legacy `performance` / `quality` | same keys | still accepted |

Aliases also accepted: `auto`, `smart`, `max_quality`, `max quality`, etc. via `normalize_routing_preference()`.

### User-facing rename

| Old strategy card | New advanced preference |
|-------------------|-------------------------|
| Eco | Prefer Lowest Carbon |
| Balanced | Automatic (Recommended) |
| Max Quality | Prefer Highest Quality |

## API changes

### `POST /summarize`

- Query param `mode` default is now **`automatic`** (was `balanced`).
- New preference keys listed above; legacy keys remain valid.

### `GET /job-result/{id}`

- `SummaryResponse` may include optional `processing_insights`:
  - CRS, document type, selected model, tier, retrieval strategy label
  - escalation, carbon_optimization_applied, latency_ms, confidence
  - `reason_summary`, `routing_preference`, domain_risk, policy_version

### `GET /documents/{document_id}/routing`

- Returns persisted routing decision JSON for post-hoc inspection.

## What did not change

- CRE scoring formulas and capability floors (`cre.py`)
- Intelligent Router utility math beyond weight-profile keys / aliases
- Carbon never overrides capability floors

## Frontend

- `strategy-selector.tsx` removed
- New: `smart-routing-panel.tsx`, `advanced-routing-settings.tsx`, `processing-insights.tsx`
- New job flow: upload → Smart Routing card → Process document
- Results: Processing Insights panel; RAG chat surfaces AnswerEnvelope fields

## Rollout order

1. Backend preference aliases + `processing_insights` (old clients still send `balanced` / `eco`)
2. Frontend Smart Routing default (`mode=automatic`)
3. This document for operators / client authors
