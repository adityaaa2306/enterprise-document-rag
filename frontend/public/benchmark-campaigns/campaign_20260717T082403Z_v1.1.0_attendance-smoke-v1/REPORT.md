# GPT Benchmark Report — `campaign_20260717T082403Z_v1.1.0_attendance-smoke-v1`

## Campaign information

- **Campaign ID:** `campaign_20260717T082403Z_v1.1.0_attendance-smoke-v1`
- **Suite:** `smoke`
- **Document ID:** `ef0f2f66-92cc-4bdc-bee2-e228132329ae`
- **Timestamp (UTC):** `2026-07-17T08:24:18.780788+00:00`
- **Finished (UTC):** `2026-07-17T08:25:52.663042+00:00`
- **Dry run:** `False`
- **Max tokens:** `500`
- **Temperature:** `0.2`

## Models evaluated

- `gpt-5-nano`
- `gpt-5-mini`
- `gpt-5.5`

## Benchmark methodology

Each question retrieves context **once** via the production retrieval pipeline. The resulting context and prompt are frozen (`context_hash`, `prompt_hash`) and validated before every model call so all models receive identical inputs. Generation uses OpenAI Chat Completions (streaming) and is isolated from Interactive RAG / ResponseAgent.

| Version field | Value |
|---|---|
| Benchmark version | `1.1.0` |
| Retrieval version | `hybrid-rrf-rerank-v1` |
| Prompt version | `qa-frozen-v1` |

## Overall statistics

- **Questions:** 5
- **Models:** 3
- **Total prompt tokens:** 29991
- **Total completion tokens:** 5408
- **Total tokens:** 35399
- **Total benchmark cost (USD):** $0.091260
- **Total benchmark runtime (s):** 93.88

## Per-model statistics

| Model | Avg latency (ms) | p50 | p95 | Avg TTFT (ms) | Avg tok/s | Avg prompt tok | Avg completion tok | Total cost (USD) | Avg energy (Wh) | Avg CO₂e (g) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `gpt-5-nano` | 5811.81 | 4443.90 | 9450.01 | 3935.37 | 87.85 | 1999.4 | 463.0 | 0.001426 | 0.6935 | 0.3537 |
| `gpt-5-mini` | 5870.49 | 6612.37 | 7323.35 | 3698.46 | 65.19 | 1999.4 | 396.0 | 0.006459 | 1.9780 | 1.0088 |
| `gpt-5.5` | 4334.66 | 5280.14 | 6031.60 | 2413.87 | 48.43 | 1999.4 | 222.6 | 0.083375 | 4.6387 | 2.3657 |

## Highlights

- **Fastest model (avg latency):** `gpt-5.5` (4334.663 ms)
- **Lowest estimated cost:** `gpt-5-nano` (0.001 USD)
- **Lowest estimated CO₂e:** `gpt-5-nano` (0.354 g)
- **Total benchmark runtime:** 93.88 s
- **Total benchmark cost:** $0.091260

## Reproducibility anchors

Every question stores `document_id`, `context_hash`, and `prompt_hash`. Re-run the same campaign configuration against the same ingested document to reproduce identical inputs for all models.

| Question | Context hash (12) | Prompt hash (12) | Chunks |
|---|---|---|---:|
| What is the main purpose of this application? | `e5fc749e4ba3` | `d135b8ab507a` | 2 |
| Who are the primary users or stakeholders? | `5fd57b98c9ea` | `b0ad639cf500` | 3 |
| List the key features described in the document. | `fa3a41079bc5` | `723d2ce37497` | 4 |
| How does attendance tracking work according to the document? | `4f4c8607da26` | `9b102438efaf` | 4 |
| What technologies or stack components are mentioned? | `e5fc749e4ba3` | `7a2d3d4a95ac` | 2 |

---

*Generated automatically by `src.eval.gpt_benchmark` — offline evaluation only; not part of the production Interactive RAG path.*
