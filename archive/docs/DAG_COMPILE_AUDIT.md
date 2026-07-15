# DAG compile execution audit (investigation only — no optimization yet)

## Scope

Audit of the DAG execution engine only. Summarization prompts/quality unchanged.
Instrumentation added to prove execution order and post-DAG wall time.

---

## Q1 — Does executive start while regional is still 0/30?

### Runnable gate (code truth)

```343:346:backend/src/core/dag_scheduler.py
def _ready(n: DagNode) -> bool:
    if n.status not in ("pending", "retrying"):
        return False
    return all(nodes[d].status == "completed" for d in n.dep_ids if d in nodes)
```

A node enters the runnable wave only when **every listed dependency that exists
in `nodes` is `completed`**. Missing dep ids are silently ignored (`if d in nodes`).

### Verdict

**True early start of the executive node on unfinished own deps: unlikely** for a
well-linked graph. Depth-ordered waves prefer shallower (regional) nodes first.

**What you actually see in the UI is usually not executive starting early.**

The job message `"Compiling executive summary... · {model}"` is stamped by
`models._hierarchical_compile` for **every** `run_compile_with_models` call —
including **regional and chapter** nodes:

```1957:1965:backend/src/agents/models.py
jobs_db.set_progress(job_id, 88.0, f"Compiling executive summary... · {chain[0]}")
```

So when the first regional LLM call begins, the status message already says
“executive” while `partial.dag.regional` can still show `0/30` (or `0/N` with
one running).

**Proof instrumentation (now live):**

- Each compile stamp logs `[DAG AUDIT] misleading progress stamp kind=regional …`
  when the real node kind ≠ `executive`.
- Latency meta: `dag_audit_misleading_executive_msgs`.
- Submit events record `dep_statuses`; unfinished deps while `running` emit
  `DAG AUDIT: node … marked running with unfinished deps`.

---

## Q2 — Why does “Compiling executive summary…” repeat while regionals run?

### Causes (ranked)

| Cause | Mechanism |
|-------|-----------|
| **Misleading stamp** | Every regional/chapter/executive LLM call overwrites the same message |
| **Overflow deferral** | Node marked running → `ensure_prompt_budget` inserts deps → deferred → later wave re-submits → stamp again |
| **Wave passes** | Up to 64 passes; pending nodes re-enter |
| **Capacity retries** | `max_attempts=2` + rate-limit requeues |
| **QVA medium→heavy** | Second `_one()` inside `_compile_node_text` stamps again |
| **Branch recompute** | Up to 3 weak nodes re-run after waves |
| **Final multi-root merge** | Extra `run_compile_with_models` if multiple executives |

DAG’s own progress text is `"DAG compile — regional: a/b, chapter: …"` — that is
honest. The repeated “executive” string is from the models layer, not from the
scheduler starting the executive node early over and over (though re-submit of
true executive can also happen via deferral/recompute).

**Proof:** `dag_audit.submit_counts[nid] > 1` and `compile_progress_stamps` list
kind+nid per stamp.

---

## Q3 — Why does regional count grow 30 → 32 → 34?

### Not “repair” kind nodes

Unified DAG does **not** insert `kind="repair"` nodes. Growth comes from
**overflow** inserts:

```361:370:backend/src/core/pipeline_dag.py
node = DagNode(
    id=nid,  # {parent}-ovf-{batch}-{seq}
    kind="chapter" if parent.kind == "executive" else "regional",
    ...
)
```

### Why mid-run

1. `pipeline_executor` builds hierarchy + `ensure_prompt_budget` (may insert).
2. `run_dag_compile` → `build_compile_dag` → **`build_hierarchy_onto_chunks` again**
   (rewrites deps; prior overflow can become orphaned).
3. Pre-exec `ensure_prompt_budget` again → more inserts.
4. Mid-run `_run_payload` calls `ensure_prompt_budget` again → more inserts;
   parent is deferred until new children complete.

Overflow regionals are mixed into the same `by_kind.regional` total the UI shows.

**Instrumentation now separates:**

- `snapshot.baseline` / `snapshot.overflow`
- `regional_baseline` / `regional_overflow`
- Progress msg appends `· ovf regional +N (base M)` when overflow > 0
- `dag_audit.overflow_inserts` + `node_count_history` phases:
  `after_build_compile_dag`, `after_pre_exec_ensure_prompt_budget`,
  `mid_run_overflow_under_{nid}`, `compile_complete`

---

## Q4 — ~5 minutes between “DAG complete” and job completion

### Path after DAG returns

```
execute_document_dag → store_for_rag → finalize_metrics → END
```

### Instrumented steps (logs: `[critical-path] START/END`)

**post_dag**

| Step | What | Typical risk |
|------|------|--------------|
| `embed_prefetch_wait` | `get_embed_prefetch(..., timeout_sec=90)` | **up to 90s hard wait** |
| `store_document_data` | SQL + sync `embed_texts` if prefetch miss + Chroma upsert + BM25 | **minutes** on large docs |

**finalize**

| Step | What |
|------|------|
| `flush_progress` | DB flush |
| `calculate_carbon_savings` | Carbon report |
| `log_job_metrics` | Metrics |
| `routing_telemetry` | Telemetry |
| `update_document_carbon_meta` | Carbon/routing patch |

Also look for `[critical-path] sync_embed document=… texts=N ms=…` inside store.

### Highest-confidence explanation for ~5 min

`embed_prefetch_wait` (≤90s) + full sync embed of all chunks when prefetch incomplete
+ Chroma/BM25. This is **after** DAG compile, while the UI may still show a stale
“Compiling executive…” message until progress is forced to “Indexing for search…”.

Note: work *inside* `run_dag_compile` after waves (branch recompute ×3, each with
90s hard isolation) can also look like “stuck after DAG” if the UI already showed
high progress — that is still **pre-return**.

---

## Critical-path diagram (wall clock)

```
Map chunks ████████████████
QVA/escalate ██
Hierarchy build █
Regional compiles ████████████████████   ← message wrongly says "executive"
Overflow inserts (+2,+2,…) █             ← regional total grows
Chapter / executive compiles ████████
Branch recompute (≤3) ████?
── DAG returns / "DAG complete" ──
embed_prefetch_wait ████████████         ← up to 90s
sync_embed + Chroma + BM25 ████████████████  ← often the multi-minute tail
finalize (carbon/telemetry/DB) █
── job complete ──
```

---

## How to read proof on the next job

1. Restart backend (pick up instrumentation).
2. Run a document that previously showed the symptoms.
3. Grep logs for:
   - `[DAG AUDIT] misleading progress stamp`
   - `[DAG AUDIT] overflow_inserts=`
   - `nodes submitted >1 time`
   - `[critical-path] START/END post_dag`
   - `[critical-path] sync_embed`
4. Inspect latency JSON meta:
   - `post_dag_breakdown`, `finalize_breakdown`
   - `dag_audit_node_count_history`
   - `dag_audit_misleading_executive_msgs`

**No optimizations applied in this pass** — instrumentation + report only.
