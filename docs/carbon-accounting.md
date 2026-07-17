# Carbon Accounting

How Green Agentic RAG estimates operational CO₂e, what is included, and why Document Processing and Interactive RAG are reported separately.

---

## 1. Why two numbers?

| Workload | When it happens | What users see |
|----------|-----------------|----------------|
| **Document Processing** | Once per upload (ingest + summarize) | Optimized / Baseline / saved · *One-time ingestion cost* |
| **Interactive RAG** | Every chat question | g CO₂e / query · session total |

A **Lifetime Carbon** total may appear as a *derived* sum (`document + session`). It is not a third measurement and is never the primary metric.

Mixing chat into the job’s Optimized/Baseline tiles would make the document look “dirtier” every time someone asks a question — so the system keeps the accounts independent.

---

## 2. Reporting boundary (Boundary A)

| Boundary | Status | Includes | Excludes |
|----------|--------|----------|----------|
| **A — Operational** | Implemented | Inference, embeddings, light CPU parse/chunk, retrieval/routing stubs, facility electricity via PUE | Training, manufacturing, end-of-life |
| B — Embodied | Reserved | — | — |
| C — Full LCA | Reserved | — | — |

Providers do not expose metered joules per request. Values are **estimates** with documented assumptions — not lab meters.

---

## 3. Shared equation

Both estimators use the same energy model:

```
E_compute (J)  = Σ (tokens × J/token for that stage or tier)
E_facility (J) = E_compute × PUE × INFRASTRUCTURE_FACTOR
E (kWh)        = E_facility / 3_600_000
CO₂e (g)       = E (kWh) × grid_intensity (gCO₂e/kWh)
```

Grid intensity comes from the **Region Scheduler** (Electricity Maps for the configured zone), with a configured fallback if live data is unavailable. Accounting code does not call Electricity Maps itself.

### Typical assumptions

Constants live in `backend/src/carbon/assumptions.py`:

| Parameter | Typical | Meaning |
|-----------|---------|---------|
| PUE | 1.15 | Facility energy / IT energy |
| Infrastructure factor | 1.0 | No silent second multiplier |
| Light J/token | ~0.85 | Smaller instruct models |
| Medium J/token | ~2.55 | Anchored to GPT-4o-mini literature (arXiv:2505.09598) |
| Heavy J/token | ~6.5 | Frontier / ~70B class |
| Embedding J/token | 0.05 | Encoder |
| Parse / chunk | very small | Local CPU stubs |

---

## 4. Document Processing: Optimized vs Baseline

Implemented by `estimate_workflow_carbon(...)`. This populates job `carbon_data` on Results and dashboards.

### Comparison design

Only **model allocation** differs; document and shared stages stay the same:

```
BASELINE                          OPTIMIZED
────────────────────────────      ────────────────────────────
Same document                     Same document
Same parse / chunk / embed        Same shared stages
Same map + compile token mass     Same token mass
ALL inference @ heavy/frontier    Per-chunk Light/Medium/Heavy
NO CRE / routing                  CRE + adaptive routing
```

### Formulas users see

```
Carbon Saved (g) = Baseline − Optimized     (signed)
Reduction %      = Carbon Saved / Baseline × 100
```

If Optimized ≥ Baseline, the UI reports **Increased emissions** (not clamped to zero). That can happen when almost every chunk routes heavy and a small routing stub is added.

### What Optimized includes

- Shared stages (parse, chunk, embed, retrieval stub, verify)  
- Map energy: sum over chunks of `(chunk tokens × J/token of that chunk’s tier)`  
- Compile at the selected compile tier  
- Small routing orchestration stub  

### Frontier “what if” chart

Each bar answers: *if the entire workflow ran on this one model, what would CO₂e be?*  
Our system bar = Optimized (routed). Naive baseline ≈ heavy / GPT-4 class.

---

## 5. Interactive RAG: per-query estimate

Implemented by `estimate_rag_query_carbon(...)` (and helpers that read ResponseAgent latency/token meta).

Stages typically include:

1. Query embedding (when applicable)  
2. Retrieval  
3. Prompt inference  
4. Completion inference  

Returned fields (API `carbon` object, optional for compatibility): estimated CO₂e, energy, grid intensity, stage breakdown, methodology text.

**Important:** this never writes into job `carbon_data`. Chat and ingest stay independent.

---

## 6. How to read the UI

**Results page** — Document Processing only:

- Optimized / Baseline / Carbon saved  
- Subtitle: one-time ingestion (parse, chunk, embed, routed summarize, compile)  
- Interactive RAG is accounted in chat  

**Chat — Carbon Accounting panel:**

```
Document Processing     X g     One-time ingestion cost
Interactive RAG         Y g/q   Session total · N questions
Lifetime Carbon         X + session   (derived · not primary)
```

Expandable sections explain methodology; a simple **Carbon Timeline** lists upload + each question.

---

## 7. Worked intuition

Suppose map+compile tokens are large and many chunks can safely run Light/Medium. Optimized inference joules drop far below “everything Heavy.” After PUE and grid intensity, **Carbon Saved** is large and positive.

If every chunk is Heavy and compile is Heavy, Optimized ≈ Baseline — savings near zero or slightly negative. That is expected, not a bug.

A single chat question is usually **much smaller** than ingest because it only pays for one retrieval + one generation, not the full hierarchical compile.

---

## 8. Limitations (read these)

- Estimates, not metered facility power.  
- Token counts may be approximate (`len(text)/4` style) when provider usage is missing.  
- Tier J/token relatives beyond the medium literature anchor are documented engineering judgments.  
- Single-region intensity today — not a claim of global carbon-optimal placement.  
- Empty or failed model answers can still show low energy if little text was generated — interpret quality and carbon together ([evaluation.md](./evaluation.md)).

---

## 9. Code map

| Module | Role |
|--------|------|
| `backend/src/carbon/assumptions.py` | Constants |
| `backend/src/carbon/energy_model.py` | J → kWh helpers, baseline/green packs |
| `backend/src/carbon/accounting.py` | `estimate_workflow_carbon`, `estimate_rag_query_carbon` |
| `backend/src/carbon/scheduler/` | Region decision + intensity |
| `backend/src/core/frontier_carbon_compare.py` | Frontier bars |

Canonical engineer reference: [`backend/docs/CARBON_ACCOUNTING.md`](../backend/docs/CARBON_ACCOUNTING.md).

---

## Related docs

- [architecture.md](./architecture.md)  
- [evaluation.md](./evaluation.md)  
- [benchmark-methodology.md](./benchmark-methodology.md)
