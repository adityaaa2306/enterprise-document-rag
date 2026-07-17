# GPT Benchmark Report — `campaign_20260717T104756Z_v1.4.0_lhas-summarization-standard`

## Campaign information

- **Campaign ID:** `campaign_20260717T104756Z_v1.4.0_lhas-summarization-standard`
- **Workload:** `Document Summarization`
- **Suite:** `summarization-standard`
- **Document ID:** `f3bbda03-2ac2-4e4b-bd01-7b6be7f81895`
- **Timestamp (UTC):** `2026-07-17T10:48:14.995293+00:00`
- **Finished (UTC):** `2026-07-17T10:50:04.706343+00:00`
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

- Quality scores were unavailable for this campaign (no reference answers or all evaluations skipped).

| Version field | Value |
|---|---|
| Benchmark version | `1.4.0` |
| Retrieval version | `None` |
| Prompt version | `summarize-frozen-v1` |
| Quality evaluator | `default_composite_v1` |

## Overall statistics

- **Questions:** 1
- **Models:** 4
- **Total prompt tokens:** 36090
- **Total completion tokens:** 3365
- **Total tokens:** 39455
- **Total benchmark cost (USD):** $0.072472
- **Total benchmark runtime (s):** 109.71
- **Avg quality score:** —
- **Median quality score:** —

## Per-model statistics

| Model | Avg latency (ms) | p50 | p95 | Avg TTFT (ms) | Avg tok/s | Avg prompt tok | Avg completion tok | Total cost (USD) | Avg energy (Wh) | Avg CO₂e (g) | Avg quality |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `Intelligent Router` | 75526.95 | 75526.95 | 75526.95 | 557.83 | 12.78 | 10116.0 | 965.0 | 0.000665 | 3.0388 | 1.6501 | — |
| `gpt-5-nano` | 6205.15 | 6205.15 | 6205.15 | — | 128.93 | 8658.0 | 800.0 | 0.000753 | 2.5981 | 1.4108 | — |
| `gpt-5-mini` | 9365.09 | 9365.09 | 9365.09 | 4585.48 | 85.42 | 8658.0 | 800.0 | 0.003765 | 7.7416 | 4.2037 | — |
| `gpt-5.5` | 10951.05 | 10951.05 | 10951.05 | 2052.17 | 73.05 | 8658.0 | 800.0 | 0.067290 | 19.6685 | 10.6800 | — |

## Highlights

- **Fastest model (avg latency):** `gpt-5-nano` (6205.153 ms)
- **Lowest estimated cost:** `intelligent-router` (0.001 USD)
- **Lowest estimated CO₂e:** `gpt-5-nano` (1.411 g)
- **Best quality model:** —
- **Total benchmark runtime:** 109.71 s
- **Total benchmark cost:** $0.072472

## Reproducibility anchors

Every question stores `document_id`, `context_hash`, and `prompt_hash`. Re-run the same campaign configuration against the same ingested document to reproduce identical inputs for all models.

| Question | Context hash (12) | Prompt hash (12) | Chunks |
|---|---|---|---:|
| Generate a document summary | `586736d7d23a` | `2517fe4d6640` | 12 |

---

*Generated automatically by `src.eval.gpt_benchmark` — offline evaluation only; not part of the production Interactive RAG path.*
