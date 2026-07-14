# Pipeline Intelligence

Adaptive document processing layered on top of the stable structure parser.

## What it does

1. **Document Capability Analyzer** — pages, tokens, sections, tables/figures, reading level, technical density, scale (`tiny`→`xlarge`), complexity class
2. **Strategy Selection** — chooses map mode, hierarchy depth, verification strictness, escalation caps, carbon budget bias
3. **Intelligent routing** — per-chunk Light/Medium/Heavy from complexity **and** grid intensity (never intensity alone)
4. **Confidence escalation** — only failed/low-confidence chunks climb Light→Medium→Heavy
5. **Adaptive hierarchy** — fan-in / max-depth / skip-regional from strategy
6. **Branch validation** — recompile weakest regional branches only (not full document)
7. **Explainability report** — why strategy / models / depth / estimates
8. **Dashboard** — Pipeline Intelligence panel on results page

## Graph

```
triage → extract_features → plan_pipeline → cre_and_route → map
  → validate ⇄ escalate → reduce_compile → store → finalize
```

## Config

- `PIPELINE_INTELLIGENCE_ENABLED=true`
- `PIPELINE_INTEL_POLICY_VERSION=intel-v1`

## Benchmark

```bash
cd backend
python -m src.eval.pipeline_intelligence_bench
```

| Scale | Strategy (automatic) |
|-------|----------------------|
| tiny | single_pass_compact |
| small | map_reduce_standard |
| medium | hierarchical_map_regional |
| large | multi_level_tree |
| xlarge | deep_tree_summarize |

Structure parser / heading detection are **not** modified by this layer.
