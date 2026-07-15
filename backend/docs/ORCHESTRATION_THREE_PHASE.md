# Three-phase orchestration (Planning → Execution → Background)

## Architecture

```
Planning (deterministic, pre-LLM compile)
  └─ hierarchy + overflow prediction → FREEZE DAG
Execution (immutable)
  └─ workers run ready nodes only; no topology edits
Summary Ready
  └─ result published immediately
Background Services (async)
  └─ embeddings, Chroma, BM25, carbon, telemetry
```

## Critical path (summary)

Planning → Map → QVA → Plan/Freeze compile DAG → Regional → Chapter → Executive → Final → **Summary Ready**

Not on critical path: embed wait, Chroma, BM25, carbon aggregation, metrics.

## Frozen DAG rules

After `plan_compile_hierarchy()`:

- No `ensure_prompt_budget()` during execution
- No `build_hierarchy_onto_chunks()` rebuild inside `run_dag_compile`
- No mid-run overflow inserts / dep rewrites
- Node count before == after (asserted)
- Repairs go through `RepairQueue` (re-run existing ids only)

## Progress messages

Compile stamps use real node kind:

- Compiling Regional Summary…
- Compiling Chapter Summary…
- Compiling Executive Summary…

## Graph wiring

`execute_document_dag` → `deliver_summary` → END

`store_for_rag` / `finalize_metrics` are invoked from `background_services`, not the LangGraph critical path.

## Modules

| Module | Role |
|--------|------|
| `src/core/planning.py` | Plan + freeze + immutability asserts |
| `src/core/repair_queue.py` | Quality repairs without topology mutation |
| `src/core/background_services.py` | Post-summary async store/finalize |
| `src/core/pipeline_executor.py` | Plan then frozen `run_dag_compile` |
| `src/core/dag_scheduler.py` | `frozen_plan=` immutable execution mode |

## Tests

`tests/test_frozen_dag_orchestration.py` — freeze, mutation detection, repair queue, overflow snapshot fields.
