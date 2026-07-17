# Architecture

This guide explains how Green Agentic RAG is put together: what runs where, how a document becomes a summary and a searchable index, and how chat stays separate from ingestion.

---

## 1. What the system is

Green Agentic RAG is a **document intelligence platform** that:

1. **Ingests** a PDF or text file through a multi-agent pipeline (chunk → route → summarize → compile).
2. **Reports** operational carbon for that job (Document Processing CO₂e).
3. **Answers questions** over the same document via retrieval-augmented generation (Interactive RAG), with **separate** per-query carbon.

The design bet: choose the *smallest capable model* per chunk (and per query path), prove quality with validation/escalation, and make emissions **measurable and explained** — not a vague “green” badge.

---

## 2. High-level stack

```
Browser (Next.js)
    │  HTTPS / REST + SSE
    ▼
API (FastAPI) ─── Auth / Guest owner ─── Job queue
    │
    ├── Model path: CRE → chunk router → map/compile → QVA
    ├── Region path: Region Scheduler → grid intensity
    ├── Carbon: Boundary-A estimators (job + RAG)
    └── Storage: Postgres/SQLite · Chroma · object storage (R2/local)
              │
              ▼
         NVIDIA NIM (+ fallbacks) · local NLI / QVA
```

| Layer | Typical tech |
|-------|----------------|
| Frontend | Next.js, TypeScript, Tailwind, Radix UI |
| API | FastAPI, JWT auth, guest sessions |
| Orchestration | LangGraph-style agent graph + frozen compile DAG |
| Models | NVIDIA NIM Light / Medium / Heavy, Nemotron embed & rerank |
| Vectors | Chroma (embedded or server) |
| Grid data | Electricity Maps via Region Scheduler (single live region today) |

---

## 3. Two independent schedulers

These must not be conflated:

| Scheduler | Question it answers | Lives in |
|-----------|---------------------|----------|
| **Region Scheduler** | *Where* is intensity measured for accounting? | `backend/src/carbon/scheduler` |
| **Model Scheduler** | *Which* Light/Medium/Heavy model runs this work? | CRE, chunk router, intelligent router, orchestrator |

Carbon accounting **never** calls Electricity Maps HTTP APIs directly. Intensity flows:

`RegionScheduler → CarbonProvider → GridCarbonData → estimate_*_carbon`

**Honesty note:** live mode is **single-region** (configured zone, e.g. India / EM free tier). The UI does not pretend every job hops continents.

---

## 4. Document Processing (ingestion)

This is the **one-time job** after upload.

### 4.1 Pipeline stages

```
Upload
  → Triage (extract text / OCR as configured)
  → Adaptive / section-aware chunking
  → Document + per-chunk feature extraction
  → CRE (capability floors) + per-chunk adaptive router
  → Parallel Map (Light / Medium / Heavy summarizers)
  → Quality Validation Agent (QVA) — escalate failed chunks only
  → Plan & freeze compile DAG (immutable)
  → Hierarchical compile (regional → chapter → executive)
  → Summary Ready  ← user-visible critical path ends here
  → Background: embeddings, Chroma/BM25, carbon finalize, telemetry
```

### 4.2 Three-phase orchestration

| Phase | Behavior |
|-------|----------|
| **Planning** | Build hierarchy and **freeze** a compile DAG before heavy execution |
| **Execution** | Workers run ready nodes only; topology does not mutate mid-run |
| **Background** | After Summary Ready: vectors, carbon aggregation, extra metrics |

Repairs (quality retries) re-run existing node ids via a repair queue — they do not rewrite the DAG shape during a run.

### 4.3 Capability Requirement Engine (CRE)

CRE scores how capable a model must be for the document (CRS) and applies **domain floors** (e.g. medical). Rough bands:

| Tier | Role |
|------|------|
| Light | Easy / short / low CRS chunks |
| Medium | Typical narrative / mid CRS |
| Heavy | Hard content, high CRS, or floor-forced |

**Carbon never overrides capability.** Eco / Balanced / Performance modes only change utility *weights*; they cannot skip summarization or drop below floors.

### 4.4 Per-chunk routing + QVA

Chunks get their own features and may route differently from the document-level tier. If QVA fails (lexical/semantic/entity checks), the chunk escalates up the ladder within a configured max. An optional **carbon budget** constrains routing; it does **not** invent a second CO₂ formula.

### 4.5 Hierarchical compile

Chunk summaries feed a planned hierarchy (regional → chapter → executive). Compile is often medium-first, with heavy compile only when quality requires it. Live Job Status progress is **cycle-scoped** so later compile stages remain visible after an earlier “Completed.”

---

## 5. Interactive RAG (chat)

Chat is a **separate path** from the ingest DAG. It does not re-run map/compile.

```
Question
  → Hybrid retrieval (dense + sparse / RRF + rerank)
  → Context pack (token budget by tier)
  → ResponseAgent (plan + LLM; streaming or blocking)
  → Optional explainability (citations, confidence, reasoning path)
  → Attach Interactive RAG carbon (optional `carbon` on the response)
```

Endpoints: `POST /rag-query`, `POST /rag-query/stream` (SSE). Session totals (queries, cumulative CO₂e) live in the chat UI and reset on **New chat**. They never mutate job `carbon_data`.

---

## 6. Frontend surfaces

| Surface | Purpose |
|---------|---------|
| New Job | Upload + eco/balanced/performance |
| Results | Summary, Document Processing carbon, routing/region tabs |
| Chat | Streaming RAG + Carbon Accounting panel (doc vs RAG vs lifetime) |
| Dashboard | Job history / aggregates |
| Benchmarks | Offline campaign explorer (static JSON under `public/benchmark-campaigns`) |

---

## 7. Backend module map

| Area | Path | Role |
|------|------|------|
| API | `backend/src/api/` | HTTP, SSE, auth, schemas |
| Orchestrator | `backend/src/core/orchestrator.py` | Agent state machine |
| Planning / DAG | `planning.py`, `pipeline_executor.py`, `dag_scheduler.py` | Freeze + immutable compile |
| CRE / routing | `cre.py`, `chunk_router.py`, `intelligent_router.py` | Capability + utility |
| Agents | `backend/src/agents/` | NIM calls, ResponseAgent, QVA |
| Retrieval | `backend/src/retrieval/`, `context/` | Search + pack |
| Carbon | `backend/src/carbon/` | Assumptions, energy, accounting, region scheduler |
| Memory / storage | `memory/`, `storage/` | Docs, chunks, vectors |
| Eval | `backend/src/eval/` | Frozen-input benchmarks |

---

## 8. Design principles

1. **Capability before carbon** — floors and QVA beat blind demotion.  
2. **Separate workloads** — Document Processing ≠ Interactive RAG in accounting and UI.  
3. **One energy methodology** — same J/token × PUE × intensity helpers.  
4. **Signed savings** — if routing loses to a naive frontier baseline, show increased emissions.  
5. **No fake global routing** — single-region honesty until multi-region is real.  
6. **Critical-path discipline** — Summary Ready before background embed/carbon.  
7. **Explainability** — routing reasons, citations, methodology in API and UI.

---

## Related docs

- [carbon-accounting.md](./carbon-accounting.md) — estimation math  
- [benchmark-methodology.md](./benchmark-methodology.md) — how campaigns are run  
- [deployment.md](./deployment.md) — how to run and ship  
- Engineer notes: [`backend/docs/ADAPTIVE_PIPELINE.md`](../backend/docs/ADAPTIVE_PIPELINE.md), [`ORCHESTRATION_THREE_PHASE.md`](../backend/docs/ORCHESTRATION_THREE_PHASE.md), [`REGION_SCHEDULER.md`](../backend/docs/REGION_SCHEDULER.md)
