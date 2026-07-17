# Executive Summary — Router vs GPT Benchmark Study (2026-07-17)

**Framework:** v1.4.0 · **Document:** Student Attendance App.pdf · **Participants:** Intelligent Router, GPT-5 nano, GPT-5 mini, GPT-5.5

## Campaigns executed
- **Document Summarization** — `summarization-standard` → `campaign_20260717T093516Z_v1.4.0_summarization-standard` ($0.065, 87 s)
- **Interactive RAG** — suite `full` / label `rag-standard` → `campaign_20260717T093705Z_v1.4.0_rag-standard` ($0.290, 917 s)

## Measured winners

| Criterion | Summarization | Interactive RAG |
|---|---|---|
| Fastest | GPT-5 nano (5.3 s)* | GPT-5 nano (4.3 s avg) |
| Highest quality | GPT-5.5 (40.0) | GPT-5.5 (44.1) |
| Lowest est. cost | Intelligent Router ($0.00052) | Intelligent Router ($0.0020 total) |
| Lowest est. CO₂e | Router among non-empty* | Intelligent Router (0.33 g/q) |
| Best trade-off | **Intelligent Router** | **Intelligent Router** |

\*GPT-5 nano produced an **empty** summarization output (quality 0) despite lowest latency.

## Intelligent Router vs GPT-5.5 (best quality baseline)

| | Summarization | Interactive RAG |
|---|---|---|
| Quality retained | **88%** of GPT-5.5 | **83%** of GPT-5.5 |
| Est. cost | **~99% lower** | **~99% lower** |
| Est. CO₂e | **~86% lower** | **~86% lower** |
| Latency | **+204%** (slower) | **+667%** (slower) |

## One-line verdict
The Intelligent Router is the measured **cost/carbon/quality-retention** trade-off winner; GPT-5.5 is the **quality** winner; GPT-5 nano is the **speed** winner but not a reliable quality baseline in this study.

Full report: [`STUDY_2026-07-17_router_vs_gpt.md`](./STUDY_2026-07-17_router_vs_gpt.md)
