# GPT Benchmark Report — `campaign_20260717T093516Z_v1.4.0_summarization-standard`

## Campaign information

- **Campaign ID:** `campaign_20260717T093516Z_v1.4.0_summarization-standard`
- **Workload:** `Document Summarization`
- **Suite:** `summarization-standard`
- **Document ID:** `ef0f2f66-92cc-4bdc-bee2-e228132329ae`
- **Timestamp (UTC):** `2026-07-17T09:35:24.800839+00:00`
- **Finished (UTC):** `2026-07-17T09:36:51.981400+00:00`
- **Dry run:** `False`
- **Max tokens:** `800`
- **Temperature:** `0.3`

## Models evaluated

- `intelligent-router`
- `gpt-5-nano`
- `gpt-5-mini`
- `gpt-5.5`

## Benchmark methodology

Document chunks are loaded **once** from storage (read-only). Parsed content, chunk boundaries, and the summarization prompt template are frozen (`context_hash`, `prompt_hash`) and validated before every participant call so all participants receive identical document text — including the same optional `reference_summary` for quality scoring. The Intelligent Router uses in-process NIM + the stored RoutingDecision; GPT participants use OpenAI Chat Completions. Production summarization HTTP / DAG pipelines are not invoked.

### Quality evaluation

When a reference answer is present, a pluggable `BenchmarkEvaluator` scores each candidate on correctness, completeness, groundedness, and conciseness (0–100) and derives an overall `quality_score`. The default `default_composite_v1` evaluator uses exact match, lexical similarity (stdlib SequenceMatcher + token F1), length alignment, and context grounding — **not** embedding cosine similarity and **not** an LLM-as-a-Judge. Quality is independent of latency/cost/CO₂e: efficiency metrics measure resource use; quality metrics measure answer fidelity and grounding. Lexical metrics undervalue valid paraphrases; future evaluators (LLM judge, RAGAS, DeepEval, human) can register without changing the campaign schema.

### Quality insights

- gpt-5.5 produced the highest average quality (40.0/100) among participants with reference answers.
- The Intelligent Router achieved 88% of the highest quality score (35.4 vs 40.0) while reducing estimated cost by 99%.
- Router average latency was 204% higher than gpt-5.5.
- Router estimated CO₂e was 86% lower than gpt-5.5.
- gpt-5.5 produced the highest quality responses but required 118× the estimated cost of Intelligent Router.

| Version field | Value |
|---|---|
| Benchmark version | `1.4.0` |
| Retrieval version | `None` |
| Prompt version | `summarize-frozen-v1` |
| Quality evaluator | `default_composite_v1` |

## Overall statistics

- **Questions:** 1
- **Models:** 4
- **Total prompt tokens:** 29773
- **Total completion tokens:** 3255
- **Total tokens:** 33028
- **Total benchmark cost (USD):** $0.065369
- **Total benchmark runtime (s):** 87.18
- **Avg quality score:** 28.39
- **Median quality score:** 36.77

## Per-model statistics

| Model | Avg latency (ms) | p50 | p95 | Avg TTFT (ms) | Avg tok/s | Avg prompt tok | Avg completion tok | Total cost (USD) | Avg energy (Wh) | Avg CO₂e (g) | Avg quality |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `Intelligent Router` | 44031.42 | 44031.42 | 44031.42 | 1751.70 | 19.42 | 7735.0 | 855.0 | 0.000515 | 2.3618 | 1.2352 | 35.35 |
| `gpt-5-nano` | 5340.09 | 5340.09 | 5340.09 | — | 149.81 | 7346.0 | 800.0 | 0.000687 | 2.2413 | 1.1722 | 0.00 |
| `gpt-5-mini` | 16184.86 | 16184.86 | 16184.86 | 6697.88 | 49.43 | 7346.0 | 800.0 | 0.003436 | 6.6713 | 3.4891 | 38.18 |
| `gpt-5.5` | 14498.89 | 14498.89 | 14498.89 | 2785.10 | 55.18 | 7346.0 | 800.0 | 0.060730 | 16.9437 | 8.8615 | 40.04 |

## Highlights

- **Fastest model (avg latency):** `gpt-5-nano` (5340.091 ms)
- **Lowest estimated cost:** `intelligent-router` (0.001 USD)
- **Lowest estimated CO₂e:** `gpt-5-nano` (1.172 g)
- **Best quality model:** `gpt-5.5` (40.040 /100)
- **Total benchmark runtime:** 87.18 s
- **Total benchmark cost:** $0.065369

## Reproducibility anchors

Every question stores `document_id`, `context_hash`, and `prompt_hash`. Re-run the same campaign configuration against the same ingested document to reproduce identical inputs for all models.

| Question | Context hash (12) | Prompt hash (12) | Chunks |
|---|---|---|---:|
| Generate a document summary | `624fd7aebd30` | `55190f47fe89` | 11 |

---

*Generated automatically by `src.eval.gpt_benchmark` — offline evaluation only; not part of the production Interactive RAG path.*
