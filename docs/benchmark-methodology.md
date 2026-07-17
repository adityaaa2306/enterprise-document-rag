# Benchmark Methodology

How offline benchmarks are run so comparisons between the Intelligent Router and GPT baselines stay fair, reproducible, and auditable.

---

## 1. Goals

Benchmarks answer questions like:

- For the **same document and same prompts**, how do quality, latency, cost, and estimated CO₂e compare across models?
- Does capability-first routing retain most of frontier quality at lower estimated cost/carbon?

They are **not** live A/B tests in production traffic. Campaigns are frozen-input experiments stored as append-only artifacts.

---

## 2. Core idea: freeze once, run everyone

Fair comparison requires identical inputs:

1. **Freeze** retrieval context (and/or stored chunks) and the prompt template.  
2. **Hash** the frozen payload.  
3. Before each participant runs, a **consistency gate** checks the hash still matches.  
4. Every model sees the same context and instructions; only the generator changes.

That removes “lucky retrieval” or “different prompt wording” as confounds.

Typical prompt ids (examples from campaigns):

| Workload | Prompt id | Notes |
|----------|-----------|--------|
| Document summarization | `summarize-frozen-v1` | Frozen chunk set → one summary per model |
| Interactive RAG | `qa-frozen-v1` | Frozen retrieved context per question |

Retrieval strategy label (RAG): e.g. `hybrid-rrf-rerank-v1` — retrieve once per question, then freeze.

---

## 3. Workloads and suites

| Workload | Suite / label examples | What is measured |
|----------|------------------------|------------------|
| **Document summarization** | `summarization-standard` | One frozen summarization task × N models |
| **Interactive RAG** | `smoke`, `full` / `rag-standard` | Question suite × N models |

- **Smoke** — small question set for cheap sanity checks.  
- **Full** — larger suite (e.g. 15 questions). Quality references may exist for only a subset; other questions still contribute latency / cost / carbon.

---

## 4. Participants

Campaigns typically include:

| Participant | Role in the story |
|-------------|-------------------|
| **Intelligent Router** | System under test (NIM routing + fallbacks) |
| **GPT-5 nano** | Speed / cheap baseline |
| **GPT-5 mini** | Mid GPT baseline |
| **GPT-5.5** | Peak-quality GPT baseline |

Exact model ids are recorded in each campaign’s `metadata.json` / `config.json`.

---

## 5. Campaign lifecycle

```
Configure suite + document + models
  → Create campaign folder under benchmark_results/campaigns/
  → Freeze inputs + run participants
  → Write results.json, summary.json, dashboard.json, REPORT.md
  → Sync slim copies to frontend/public/benchmark-campaigns/
  → Benchmarks UI reads static JSON (no LLM calls)
```

### Artifact layout

```
benchmark_results/campaigns/campaign_<timestamp>_v<ver>_<label>/
  config.json
  metadata.json
  results.json          # full runs
  summary.json
  dashboard.json        # UI-friendly aggregates
  REPORT.md
  gpt_benchmark_*.json  # raw run dumps (as produced)
```

Campaign ids look like:

`campaign_20260717T093705Z_v1.4.0_rag-standard`

### Sync to the UI

```powershell
# from repo root
.\scripts\sync-benchmark-campaigns.ps1
```

This copies selected files into `frontend/public/benchmark-campaigns/` and rebuilds `index.json`. The Benchmarks page loads `/benchmark-campaigns/index.json` only — it does not re-run models.

---

## 6. Metrics collected per run

| Metric | Source |
|--------|--------|
| Latency | Wall / stage timers |
| Quality score | `BenchmarkEvaluator` (e.g. `default_composite_v1`, 0–100) when a reference exists |
| Estimated API cost | Token/pricing estimates for the participant |
| Estimated energy / CO₂e | Same Boundary-A estimators as the product ([carbon-accounting.md](./carbon-accounting.md)) |

Carbon in benchmarks is **estimated**, consistent with the app — not a separate invented formula.

---

## 7. Status and failed campaigns

The sync script marks a campaign `failed` when, for example, total API cost is `$0` on a non–dry-run (typical of an aborted run). Failed campaigns can appear in the index with a red status; they should not be used as default “best” campaigns in the UI.

Deleting a campaign means removing its folder under **both** `benchmark_results/campaigns/` and `frontend/public/benchmark-campaigns/`, then re-running the sync script.

---

## 8. Evidence culture

- Claims in study write-ups should cite **campaign artifacts**, not memory.  
- Empty answers (`ok=true` but zero-length text) must be called out — low latency/cost is not success.  
- Studies live under `benchmark_results/studies/` (and may be mirrored under `frontend/public/benchmark-campaigns/` for the UI).

---

## 9. How to run (orientation)

Exact CLI flags evolve with the eval package; typical entrypoints live at the repo root / `backend/src/eval/gpt_benchmark/`. Pattern:

```text
python run_benchmark.py --suite <suite> --filename "<doc.pdf>" --models "..." --label <label>
```

Always prefer freezing against an already-ingested `document_id` when the harness supports it, so retrieval matches production indexing.

---

## Related docs

- [evaluation.md](./evaluation.md) — how to interpret quality and trade-offs  
- [carbon-accounting.md](./carbon-accounting.md) — Boundary-A estimators used in campaigns  
- Example study: [`benchmark_results/studies/STUDY_2026-07-17_router_vs_gpt.md`](../benchmark_results/studies/STUDY_2026-07-17_router_vs_gpt.md)
