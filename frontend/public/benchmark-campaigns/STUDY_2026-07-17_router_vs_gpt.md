# Intelligent Router vs GPT Baselines — Benchmark Study

**Study date (UTC):** 2026-07-17  
**Benchmark framework:** v1.4.0  
**Document:** Student Attendance App.pdf (`ef0f2f66-92cc-4bdc-bee2-e228132329ae`)  
**Participants:** Intelligent Router · GPT-5 nano · GPT-5 mini · GPT-5.5  
**Evaluator:** `default_composite_v1` (lexical composite; 0–100)  
**Evidence basis:** Measured campaign artifacts only — no unsupported claims.

---

## Executive summary

Two live campaigns were executed with identical frozen-input methodology:

| Campaign | Workload | Suite / label | Runs | Wall time | Est. spend |
|---|---|---|---:|---:|---:|
| `campaign_20260717T093516Z_v1.4.0_summarization-standard` | Document Summarization | `summarization-standard` | 4 (1×4) | 87.2 s | **$0.0654** |
| `campaign_20260717T093705Z_v1.4.0_rag-standard` | Interactive RAG | suite `full`, label `rag-standard` | 60 (15×4) | 916.5 s | **$0.2900** |

**Headline findings (measured):**

1. **GPT-5.5** produced the **highest quality** on both workloads (summarization **40.0**/100; RAG **44.1**/100 on scored questions).
2. The **Intelligent Router** retained **88%** (summarization) and **83%** (RAG) of GPT-5.5’s quality while cutting estimated API cost by **~99%** vs GPT-5.5 on both workloads.
3. **GPT-5 nano** was the **fastest** participant on both workloads, but frequently returned **empty / zero-quality** answers under this frozen-prompt setup — speed alone is not a usable trade-off here.
4. On **estimated CO₂e**, the Intelligent Router was **lowest among participants that produced non-empty answers** on summarization, and **lowest overall** on RAG (avg **0.329 g**/query vs GPT-5.5 **2.406 g**/query).
5. Router **latency** was substantially higher than GPT baselines (summarization **+204%** vs GPT-5.5; RAG **+667%** vs GPT-5.5), driven by in-process NIM routing with a first-model timeout then fallback to `meta/llama-3.1-8b-instruct`.

**Engineering trade-off judgment (from these artifacts):** the Intelligent Router occupies the **cost / carbon / quality-retention** region of the Pareto set; GPT-5.5 occupies **peak quality**; GPT-5 nano occupies **peak speed** but not reliable answer quality in this study.

---

## 1. Methodology (unchanged framework)

### Shared protocol
- Freeze inputs once; hash context + prompt; consistency gate before every participant.
- Same participants, same document, same reference material where available.
- Quality via existing `BenchmarkEvaluator` (`default_composite_v1`).
- Carbon / energy via existing Boundary-A estimators (not live meters).
- Campaigns are append-only under `benchmark_results/campaigns/`.

### Document Summarization (`summarization-standard`)
- Frozen stored chunks (11/11, 30 478 chars), prompt `summarize-frozen-v1`.
- One summarization task × 4 participants.
- Reference summary: built-in attendance reference (`dataset-id=attendance_smoke`).

### Interactive RAG (`rag-standard`)
- Existing suite **`full`** (15 questions) with campaign label **`rag-standard`** — no new suite code.
- Retrieve-once per question; prompt `qa-frozen-v1`; retrieval `hybrid-rrf-rerank-v1`.
- Quality references available for the **5 smoke questions** only (`n_quality_scored=5` per model); remaining 10 questions contribute latency/cost/carbon but not quality averages.

### Artifact locations
- Summarization: `benchmark_results/campaigns/campaign_20260717T093516Z_v1.4.0_summarization-standard/`
- RAG: `benchmark_results/campaigns/campaign_20260717T093705Z_v1.4.0_rag-standard/`
- Dashboard sync: `frontend/public/benchmark-campaigns/`

---

## 2. Document Summarization — results

### Per-participant aggregates (1 run each)

| Participant | Avg latency (ms) | Quality | Est. cost (USD) | Est. energy (Wh) | Est. CO₂e (g) | Summary length (chars) |
|---|---:|---:|---:|---:|---:|---:|
| Intelligent Router | 44 031 | **35.35** | **0.000515** | 2.362 | 1.235 | 3 420 |
| GPT-5 nano | **5 340** | 0.00 | 0.000687 | **2.241** | **1.172** | **0** |
| GPT-5 mini | 16 185 | 38.18 | 0.003437 | 6.671 | 3.489 | 2 083 |
| GPT-5.5 | 14 499 | **40.04** | 0.060730 | 16.944 | 8.862 | 3 643 |

Campaign total estimated spend: **$0.0654**. Wall time: **87.2 s**.

### Answers to study questions (summarization)

| Question | Winner (measured) | Value |
|---|---|---|
| Fastest? | GPT-5 nano | 5 340 ms |
| Highest quality? | GPT-5.5 | 40.04 / 100 |
| Lowest estimated cost? | Intelligent Router | $0.000515 |
| Lowest estimated CO₂e? | GPT-5 nano* | 1.172 g (*empty answer; see note) |
| Best overall trade-off? | **Intelligent Router** | 88% of GPT-5.5 quality at 0.85% of its cost; CO₂e 86% lower than GPT-5.5 |

**Note on GPT-5 nano:** the run completed `ok=true` with **empty summary text** (`summary_length=0`, quality **0.0**). Its latency/cost/CO₂e figures are therefore not evidence of a successful summarization. Among participants with non-empty summaries, **Intelligent Router** has the lowest estimated cost and CO₂e; **GPT-5.5** has the highest quality.

### Router vs best GPT baseline (GPT-5.5) — summarization

| Metric | Router | GPT-5.5 | Delta (Router vs GPT-5.5) |
|---|---:|---:|---|
| Latency (ms) | 44 031 | 14 499 | **+203.7%** (slower) |
| Quality | 35.35 | 40.04 | **88.3%** of GPT-5.5 |
| Est. cost (USD) | 0.000515 | 0.060730 | **0.0085×** (≈ **99.2%** lower) |
| Est. energy (Wh) | 2.362 | 16.944 | **0.139×** (≈ **86.1%** lower) |
| Est. CO₂e (g) | 1.235 | 8.862 | **0.139×** (≈ **86.1%** lower) |

Router path observed: primary NIM model timed out → fallback **`meta/llama-3.1-8b-instruct`** (TTFT 1 752 ms).

---

## 3. Interactive RAG — results

### Per-participant aggregates (15 questions each)

| Participant | Avg latency (ms) | p50 / p95 (ms) | Avg quality* | Total est. cost (USD) | Avg energy (Wh) | Avg CO₂e (g) |
|---|---:|---:|---:|---:|---:|---:|
| Intelligent Router | 39 129 | 39 117 / 39 944 | **36.71** | **0.002000** | **0.628** | **0.329** |
| GPT-5 nano | **4 306** | 3 843 / 5 534 | 9.04 | 0.004458 | 0.688 | 0.360 |
| GPT-5 mini | 8 810 | 8 240 / 14 363 | 25.25 | 0.020995 | 1.982 | 1.037 |
| GPT-5.5 | 5 102 | 4 753 / 8 608 | **44.14** | 0.262590 | 4.600 | 2.406 |

\*Quality averages use **5 scored questions** with reference answers (`n_quality_scored=5`). Campaign total estimated spend: **$0.2900**. Wall time: **916.5 s**. Retrieval calls: **15** (one per question).

### Answers to study questions (Interactive RAG)

| Question | Winner (measured) | Value |
|---|---|---|
| Fastest? | GPT-5 nano | 4 306 ms avg |
| Highest quality? | GPT-5.5 | 44.14 / 100 |
| Lowest estimated cost? | Intelligent Router | $0.002000 total |
| Lowest estimated CO₂e? | Intelligent Router | 0.329 g/query avg |
| Best overall trade-off? | **Intelligent Router** | 83% of GPT-5.5 quality; ≈99% lower cost & CO₂e; latency much higher |

### Router vs best GPT baseline (GPT-5.5) — RAG

| Metric | Router | GPT-5.5 | Delta (Router vs GPT-5.5) |
|---|---:|---:|---|
| Avg latency (ms) | 39 129 | 5 102 | **+667.0%** (slower) |
| Avg quality | 36.71 | 44.14 | **83.2%** of GPT-5.5 |
| Total est. cost (USD) | 0.002000 | 0.262590 | **0.0076×** (≈ **99.2%** lower) |
| Avg est. energy (Wh) | 0.628 | 4.600 | **0.137×** (≈ **86.3%** lower) |
| Avg est. CO₂e (g) | 0.329 | 2.406 | **0.137×** (≈ **86.3%** lower) |

---

## 4. Pareto / trade-off analysis

### Frontier roles (both workloads)

| Role | Participant | Evidence |
|---|---|---|
| **Fastest** | GPT-5 nano | Lowest avg latency (sum + RAG) |
| **Highest quality** | GPT-5.5 | Highest `avg_quality_score` (sum + RAG) |
| **Cheapest** | Intelligent Router | Lowest total / per-run estimated API cost |
| **Most sustainable (est. CO₂e)** | Intelligent Router* | Lowest avg CO₂e on RAG; lowest among non-empty summaries on summarization (*nano’s lower CO₂e coincided with empty output) |
| **Best engineering trade-off** | **Intelligent Router** | High fraction of peak quality at ~1% of GPT-5.5 cost and ~14% of GPT-5.5 CO₂e |

### Interpretation
- There is **no single participant** that is simultaneously fastest, cheapest, and highest quality.
- GPT-5.5 dominates **quality**, at **~118–131×** the estimated cost of the Intelligent Router in these campaigns.
- The Intelligent Router is **not** latency-competitive with GPT APIs in this study (NIM timeout + fallback dominates wall time).
- If the product objective is **retain most quality while minimizing estimated cost and carbon**, the measured Pareto choice is the **Intelligent Router**.
- If the objective is **minimum latency**, GPT-5 nano wins on timing but **fails quality** often enough that GPT-5.5 / GPT-5 mini are the practical GPT speed–quality options.

---

## 5. Limitations

1. **Benchmark scope**  
   Single document (Student Attendance App.pdf). Summarization = one frozen window; RAG = 15 questions. Results do not generalize to all corpora or query distributions.

2. **Estimated carbon**  
   Energy and CO₂e are **Boundary-A estimates** (token × J/token × PUE × grid intensity), not metered datacenter readings. Absolute grams should be treated comparatively within this study.

3. **Quality evaluator**  
   `default_composite_v1` is lexical (exact match, SequenceMatcher + token F1, length, grounding overlap). It **undervalues valid paraphrases** and is not an LLM-as-a-Judge or human preference study. Absolute scores are moderate (~35–45) even for strong answers.

4. **Reference dataset**  
   Only the five smoke-reference items scored quality on RAG (`n_quality_scored=5`). Ten RAG questions have no reference — latency/cost/carbon still measured. Summarization used one built-in reference summary.

5. **GPT-5 nano empty outputs**  
   Several nano runs returned empty text with `ok=true` (summarization length 0; multiple RAG quality scores 0). Treat nano primarily as a **latency reference**, not a quality baseline, until prompt/API decoding behavior is characterized further.

6. **Router latency composition**  
   Observed primary-model slice timeouts (~37.7 s) before fallback inflate router latency. Comparative latency claims must note this routing/timeout behavior.

7. **Future work (not executed here)**  
   Larger multi-document campaigns; human / LLM-judge quality; RAGAS/DeepEval plug-ins; router latency tuning without changing production APIs; broader reference sets for the full question suite.

---

## 6. Outputs checklist

| Deliverable | Path / status |
|---|---|
| Summarization campaign | `benchmark_results/campaigns/campaign_20260717T093516Z_v1.4.0_summarization-standard/` ✅ |
| RAG campaign (`rag-standard`) | `benchmark_results/campaigns/campaign_20260717T093705Z_v1.4.0_rag-standard/` ✅ |
| Per-campaign `REPORT.md` / `dashboard.json` / `summary.json` | Inside each campaign folder ✅ |
| Dashboard public sync | `frontend/public/benchmark-campaigns/` (index rebuilt from remaining campaigns) ✅ |
| This study report | `benchmark_results/studies/STUDY_2026-07-17_router_vs_gpt.md` ✅ |
| Executive summary (short) | `benchmark_results/studies/EXECUTIVE_SUMMARY_2026-07-17.md` ✅ |

---

## 7. Conclusion (measured only)

Across Document Summarization and Interactive RAG on this document, **GPT-5.5** is the quality leader and **GPT-5 nano** is the latency leader (with unreliable empty answers). The **Intelligent Router** repeatedly delivered **~83–88% of GPT-5.5 quality** at **~1% of GPT-5.5 estimated cost** and **~14% of GPT-5.5 estimated CO₂e**, at the expense of **much higher latency**. For a green / cost-aware deployment objective under this frozen-input methodology, the Intelligent Router is the best measured engineering trade-off; for peak answer quality regardless of cost, GPT-5.5 remains ahead.
