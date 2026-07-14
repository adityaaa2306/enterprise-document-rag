# Adaptive Hierarchical Carbon-Aware Summarization Pipeline

## Overview

This document describes the extended ingest pipeline that adds per-chunk
routing, Light→Medium→Heavy escalation, section-aware hierarchy, medium-first
compile, and a carbon budget — without changing Boundary-A carbon accounting
math (`tokens × J/token × PUE × Electricity Maps`).

## Pipeline

```
Upload → Triage → Adaptive Semantic Chunking
      → Document + Per-chunk Feature Extraction
      → CRE (document floors) + Per-chunk Adaptive Router
      → Parallel Map (Light / Medium / Heavy agents)
      → Quality Validation (lexical + semantic proxies)
      → Escalate failed chunks only (ladder, max QVA_MAX_ESCALATIONS)
      → Regional hierarchy (dynamic depth)
      → Medium compile → QVA → Heavy compile only if needed
      → Store + Boundary-A carbon accounting → Dashboard
```

## Key modules

| Module | Role |
|--------|------|
| `src/chunking/service.py` | Semantic/section-aware chunking, overlap, soft cap |
| `src/agents/chunk_features.py` | Per-chunk complexity/importance/… features |
| `src/core/chunk_router.py` | Per-chunk Light/Medium/Heavy + explanations + budget |
| `src/agents/summarization_agents.py` | Agent wrappers with latency/carbon/confidence |
| `src/agents/quality_validation.py` | QVA with semantic similarity + entity retention |
| `src/core/hierarchy.py` | Regional / dynamic hierarchy |
| `src/core/orchestrator.py` | LangGraph wiring |
| `src/eval/adaptive_benchmark.py` | Always-Heavy vs Medium vs Adaptive comparison |

## Config knobs (`src/core/config.py`)

- `CHUNK_MAX_COUNT` (default 512), `CHUNK_OVERLAP_TOKENS`, `CHUNK_FORCE_CAP`
- `ADAPTIVE_CHUNK_ROUTING`, `ADAPTIVE_REGIONAL_HIERARCHY`
- `COMPILE_MEDIUM_FIRST`
- `CARBON_BUDGET_ENABLED`, `CARBON_BUDGET_G` (default 40)
- `QVA_MAX_ESCALATIONS` (default 2), `QVA_SEMANTIC_SIM_MIN`, `QVA_ENTITY_RETENTION_MIN`
- `HEAVY_QUALITY_GAIN_MIN`

## Carbon budget

Budget is a **routing constraint**. It does not invent a second CO₂ formula.
The dashboard still reports Boundary-A estimates from `estimate_workflow_carbon`.

## Explainability

Each chunk route stores: tier, model, reason, expected quality/carbon/latency.
Job results expose `processing_insights` with routing distribution, hierarchy,
timeline, carbon budget, and agent telemetry.

## Evaluation

```bash
cd backend
python -c "from src.eval.adaptive_benchmark import compare_strategies; ..."
pytest tests/test_adaptive_pipeline_e2e.py tests/test_chunk_router.py -q
```

Optional ROUGE/BERTScore are used only when those packages are installed.
