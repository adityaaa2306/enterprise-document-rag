# Evaluation

How quality is scored, who the benchmark participants are, and how to interpret study results without over-claiming.

---

## 1. What “evaluation” means here

Two related layers:

| Layer | Purpose |
|-------|---------|
| **In-pipeline quality (QVA)** | During a live job, decide whether a chunk/summary is good enough or must escalate |
| **Offline benchmarks** | Fair, frozen-input comparison of Intelligent Router vs GPT baselines |

This guide focuses on **offline benchmarks and study interpretation**. For QVA in the live pipeline, see [architecture.md](./architecture.md).

---

## 2. Quality metric

Campaigns use a composite lexical evaluator (e.g. `default_composite_v1`) that returns a score on **0–100** when a **reference** answer/summary exists.

Important nuances:

- Not every question in a large RAG suite has a reference. Unscored items still contribute **latency, cost, and carbon** averages.  
- Scores are useful for **relative ranking** under the same frozen inputs — not absolute “human preference” or exam grades.  
- An empty model output typically scores **0** even if the HTTP call “succeeded.”

Always check `n_quality_scored` (or equivalent) in campaign metadata before trusting a quality average.

---

## 3. Participants (typical set)

| Participant | What it represents |
|-------------|--------------------|
| **Intelligent Router** | Production-shaped path: capability routing on NIM with timeouts/fallbacks |
| **GPT-5 nano** | Fast / low-cost OpenAI-class baseline |
| **GPT-5 mini** | Mid-tier OpenAI-class baseline |
| **GPT-5.5** | Highest-quality OpenAI-class baseline in recent studies |

The Router is **not** “GPT with a green label.” It is a different serving stack. Latency gaps often come from NIM timeouts and fallbacks (e.g. primary timeout → smaller instruct model), not only from “being greener.”

---

## 4. Dimensions of comparison

Studies usually report four axes:

| Axis | Prefer… | Watch out for… |
|------|---------|----------------|
| **Quality** | Higher score vs reference | Empty answers; small `n_quality_scored` |
| **Latency** | Lower ms | Fast empty answers look great and are useless |
| **Est. API cost** | Lower USD | Pricing estimates; different providers ≠ same bill |
| **Est. CO₂e** | Lower grams | Same Boundary-A model as the product; not metered power |

There is rarely a single winner on all four. The interesting claim is usually a **Pareto / trade-off** statement.

---

## 5. How to read a study (worked pattern)

Using the 2026-07-17 Router vs GPT study on *Student Attendance App.pdf* as a template (see full report in `benchmark_results/studies/`):

### Headline pattern that is valid

> Router retained ~83–88% of GPT-5.5 quality at ~1% of GPT-5.5 estimated cost and much lower estimated CO₂e, at substantially higher latency.

### Headline patterns that are **not** valid without caveats

- “Nano is best on carbon” when Nano returned an **empty** summary.  
- “Router is always faster” when measured latency was higher due to timeouts.  
- “We are multi-region carbon optimal” when the Region Scheduler is single-region.

### Quality retention

```
retention % = (Router quality / GPT-5.5 quality) × 100
```

Only meaningful when both produced non-empty answers on the same scored set.

### Cost / carbon deltas

Prefer ratios or “% lower” vs the quality leader, and state that figures are **estimates** from the shared carbon/cost helpers.

---

## 6. Interpreting empty or failed runs

| Observation | Interpretation |
|-------------|----------------|
| `ok=true`, length 0, quality 0 | Call completed; answer failed. Do not crown it on cost/carbon. |
| Campaign `status=failed`, $0 spend | Aborted / incomplete — exclude from success narratives. |
| High Router latency | Check REPORT for timeout → fallback model path. |

The Benchmarks UI marks failed campaigns; prefer successful campaigns with non-empty outputs when picking a default to explore.

---

## 7. What evaluation does *not* prove

- Human preference or factual accuracy on every domain.  
- Absolute grams of CO₂ at the data center meter.  
- That Eco mode always beats Performance on carbon (capability floors can force heavy tiers).  
- That results on one PDF generalize to all document types.

Treat each study as: **measured under frozen inputs X, suite Y, framework version Z.**

---

## 8. Where to look in the repo

| Artifact | Location |
|----------|----------|
| Campaign folders | `benchmark_results/campaigns/` |
| Study write-ups | `benchmark_results/studies/` |
| UI sync | `frontend/public/benchmark-campaigns/` |
| Methodology | [benchmark-methodology.md](./benchmark-methodology.md) |
| Carbon math | [carbon-accounting.md](./carbon-accounting.md) |

---

## Related docs

- [benchmark-methodology.md](./benchmark-methodology.md)  
- [architecture.md](./architecture.md)  
- Example: [`STUDY_2026-07-17_router_vs_gpt.md`](../benchmark_results/studies/STUDY_2026-07-17_router_vs_gpt.md)
