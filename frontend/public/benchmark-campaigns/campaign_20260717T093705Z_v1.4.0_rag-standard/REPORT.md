# GPT Benchmark Report — `campaign_20260717T093705Z_v1.4.0_rag-standard`

## Campaign information

- **Campaign ID:** `campaign_20260717T093705Z_v1.4.0_rag-standard`
- **Workload:** `Interactive RAG`
- **Suite:** `full`
- **Document ID:** `ef0f2f66-92cc-4bdc-bee2-e228132329ae`
- **Timestamp (UTC):** `2026-07-17T09:37:17.295847+00:00`
- **Finished (UTC):** `2026-07-17T09:52:33.842112+00:00`
- **Dry run:** `False`
- **Max tokens:** `500`
- **Temperature:** `0.2`

## Models evaluated

- `intelligent-router`
- `gpt-5-nano`
- `gpt-5-mini`
- `gpt-5.5`

## Benchmark methodology

Each question retrieves context **once** via the production retrieval pipeline. The resulting context and prompt are frozen (`context_hash`, `prompt_hash`) and validated before every participant call so all participants (GPT models and the Intelligent Router) receive identical inputs — including the same optional `reference_answer` for quality scoring. Generation for GPT participants uses OpenAI Chat Completions (streaming) and is isolated from Interactive RAG / ResponseAgent.

### Quality evaluation

When a reference answer is present, a pluggable `BenchmarkEvaluator` scores each candidate on correctness, completeness, groundedness, and conciseness (0–100) and derives an overall `quality_score`. The default `default_composite_v1` evaluator uses exact match, lexical similarity (stdlib SequenceMatcher + token F1), length alignment, and context grounding — **not** embedding cosine similarity and **not** an LLM-as-a-Judge. Quality is independent of latency/cost/CO₂e: efficiency metrics measure resource use; quality metrics measure answer fidelity and grounding. Lexical metrics undervalue valid paraphrases; future evaluators (LLM judge, RAGAS, DeepEval, human) can register without changing the campaign schema.

### Quality insights

- gpt-5.5 produced the highest average quality (44.1/100) among participants with reference answers.
- The Intelligent Router achieved 83% of the highest quality score (36.7 vs 44.1) while reducing estimated cost by 99%.
- Router average latency was 667% higher than gpt-5.5.
- Router estimated CO₂e was 86% lower than gpt-5.5.
- gpt-5.5 produced the highest quality responses but required 131× the estimated cost of Intelligent Router.

| Version field | Value |
|---|---|
| Benchmark version | `1.4.0` |
| Retrieval version | `hybrid-rrf-rerank-v1` |
| Prompt version | `qa-frozen-v1` |
| Quality evaluator | `default_composite_v1` |

## Overall statistics

- **Questions:** 15
- **Models:** 4
- **Total prompt tokens:** 118381
- **Total completion tokens:** 20663
- **Total tokens:** 139044
- **Total benchmark cost (USD):** $0.290042
- **Total benchmark runtime (s):** 916.54
- **Avg quality score:** 28.78
- **Median quality score:** 34.15

## Per-model statistics

| Model | Avg latency (ms) | p50 | p95 | Avg TTFT (ms) | Avg tok/s | Avg prompt tok | Avg completion tok | Total cost (USD) | Avg energy (Wh) | Avg CO₂e (g) | Avg quality |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `Intelligent Router` | 39129.19 | 39116.71 | 39944.47 | 531.19 | 4.08 | 2061.3 | 161.1 | 0.002000 | 0.6283 | 0.3286 | 36.71 |
| `gpt-5-nano` | 4305.89 | 3843.09 | 5534.40 | 4395.90 | 119.73 | 1943.6 | 500.0 | 0.004458 | 0.6883 | 0.3600 | 9.04 |
| `gpt-5-mini` | 8810.15 | 8239.97 | 14362.83 | 6137.76 | 54.94 | 1943.6 | 456.9 | 0.020994 | 1.9821 | 1.0366 | 25.25 |
| `gpt-5.5` | 5101.57 | 4753.45 | 8607.66 | 2916.36 | 50.40 | 1943.6 | 259.6 | 0.262590 | 4.5995 | 2.4056 | 44.14 |

## Highlights

- **Fastest model (avg latency):** `gpt-5-nano` (4305.887 ms)
- **Lowest estimated cost:** `intelligent-router` (0.002 USD)
- **Lowest estimated CO₂e:** `intelligent-router` (0.329 g)
- **Best quality model:** `gpt-5.5` (44.136 /100)
- **Total benchmark runtime:** 916.54 s
- **Total benchmark cost:** $0.290042

## Reproducibility anchors

Every question stores `document_id`, `context_hash`, and `prompt_hash`. Re-run the same campaign configuration against the same ingested document to reproduce identical inputs for all models.

| Question | Context hash (12) | Prompt hash (12) | Chunks |
|---|---|---|---:|
| What is the main purpose of this application? | `e5fc749e4ba3` | `d135b8ab507a` | 2 |
| Who are the primary users or stakeholders? | `5fd57b98c9ea` | `b0ad639cf500` | 3 |
| List the key features described in the document. | `fa3a41079bc5` | `723d2ce37497` | 4 |
| How does attendance tracking work according to the document? | `4f4c8607da26` | `9b102438efaf` | 4 |
| What technologies or stack components are mentioned? | `e5fc749e4ba3` | `7a2d3d4a95ac` | 2 |
| Summarize the system architecture in one paragraph. | `59d1e0b3c9c0` | `a5b0005c668d` | 2 |
| What problems does this application aim to solve? | `5fd57b98c9ea` | `1048498f8a27` | 3 |
| Describe any authentication or role-based access mentioned. | `b32f356526a4` | `dbb3af36c3b7` | 3 |
| What reports or analytics does the system provide? | `12b39e41475b` | `d8119885e9cb` | 3 |
| List any limitations, risks, or future work mentioned. | `26d029f6e110` | `6a0feac2c292` | 3 |
| How is data stored or persisted? | `b32f356526a4` | `7ae9407350ca` | 3 |
| Explain the student registration or enrollment flow. | `48d939e21d2a` | `78887d86d453` | 2 |
| What UI screens or modules are described? | `e5fc749e4ba3` | `27f7a85606b6` | 2 |
| How are absences or late arrivals handled? | `5fd57b98c9ea` | `800284a832af` | 3 |
| Provide a concise executive summary of the document. | `60220595acc1` | `740e87cc4430` | 4 |

---

*Generated automatically by `src.eval.gpt_benchmark` — offline evaluation only; not part of the production Interactive RAG path.*
