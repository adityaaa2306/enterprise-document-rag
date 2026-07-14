# Document Structure Parser

Production-grade replacement for naive PyPDF Title→parent chunking.

## Pipeline

```
Layout blocks (triage)
  → Heading Validation Engine (confidence + classification)
  → Semantic Section Builder
  → Semantic Merge (safe neighbours only)
  → Adaptive Pack (target 800, min 450, max 1200)
  → AdaptiveChunk[] for map / RAG / carbon (unchanged)
```

## Key modules

| Module | Role |
|--------|------|
| `src/structure/heading_validator.py` | Multi-signal confidence + classification |
| `src/structure/section_builder.py` | Sections until next validated heading |
| `src/structure/semantic_merge.py` | Merge only when semantically safe |
| `src/structure/packing.py` | Token-band packing without force-cap |
| `src/structure/pipeline.py` | Orchestrates → AdaptiveChunk |

## Config

- `USE_STRUCTURE_PARSER=true`
- `HEADING_CONFIDENCE_THRESHOLD=0.55`
- `STRUCTURE_TARGET_TOKENS=800`
- `STRUCTURE_MIN_TOKENS=450`
- `STRUCTURE_MAX_TOKENS=1200`
- `STRUCTURE_MERGE_SIM_MIN=0.28`

## FinalReport.pdf (observed)

| | Before | After |
|--|--:|--:|
| Titles / validated | 206 false Titles | 71 validated |
| Packed chunks | 206 | **6** |
| Median tokens | 8 | **~844** |
| Map calls | 206 | **6** |

Chunk count is natural from ~5k extractable tokens ÷ ~800 target — not a force-cap.
