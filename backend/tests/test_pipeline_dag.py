"""Unit tests for unified pipeline DAG (schema, fan-in, overflow layers)."""
from src.core.pipeline_dag import (
    DagNode,
    allow_planning_overflow,
    build_chunk_nodes,
    build_hierarchy_onto_chunks,
    compute_dynamic_fan_in,
    context_token_budget,
    ensure_prompt_budget,
    insert_overflow_layer,
    carbon_rollups,
    critical_path_ms,
    perf_metrics,
)


class _C:
    def __init__(self, content, section_path="Intro", parent_id="p1"):
        self.content = content
        self.section_path = section_path
        self.parent_id = parent_id


def test_dag_node_has_parent_children_fields():
    n = DagNode(id="a", kind="chunk", depth=0, parent_ids=["x"], children_ids=["y"])
    d = n.to_dict()
    assert "parent_ids" in d and "children_ids" in d
    assert d["parent_ids"] == ["x"]


def test_build_chunk_nodes_are_pending_not_stub_completed():
    chunks = [_C("hello world"), _C("second")]
    nodes = build_chunk_nodes(chunks, routes={0: {"tier": "light"}})
    assert len(nodes) == 2
    assert all(n.status == "pending" for n in nodes.values())
    assert nodes["chunk-0"].tier == "light"
    assert nodes["chunk-0"].kind == "chunk"


def test_tiny_single_chunk_always_gets_final_executive():
    """Regression: skip_regional_below=99 + 1 chunk must not leave a chunk-only DAG (dag_empty)."""
    chunks = [_C("Trip itinerary Ahmedabad to Pune with baggage and fare details. " * 8)]
    summaries = [
        "Extractive fallback: Ahmedabad to Pune IndiGo flight with passenger details."
    ]
    nodes = build_chunk_nodes(chunks, routes={0: {"tier": "light"}})
    nodes["chunk-0"].status = "completed"
    nodes["chunk-0"].output_summary = summaries[0]
    nodes = build_hierarchy_onto_chunks(
        nodes,
        chunks,
        summaries,
        fan_in=8,
        max_depth=2,
        skip_regional_below=99,
    )
    exec_nodes = [n for n in nodes.values() if n.kind in ("executive", "final")]
    assert exec_nodes, "expected final-executive for tiny/flat single-chunk docs"
    assert any(n.id == "final-executive" for n in exec_nodes)
    fe = nodes["final-executive"]
    assert fe.dep_ids == ["chunk-0"]
    assert fe.kind == "executive"
    assert nodes["chunk-0"].kind == "chunk"


def test_dynamic_fan_in_scales_with_chunks():
    fan_small, depth_small = compute_dynamic_fan_in(doc_tokens=2000, chunk_count=5)
    fan_large, depth_large = compute_dynamic_fan_in(doc_tokens=400_000, chunk_count=800)
    assert fan_small >= 2
    assert fan_large >= 2
    assert depth_large >= depth_small
    assert depth_large <= 16


def test_insert_overflow_layer_adds_hierarchy_not_text_split():
    from src.core.pipeline_dag import context_token_budget

    budget = context_token_budget()
    # Force total tokens well above budget
    per = max(500, (budget // 4) + 200)
    nodes = {}
    deps = []
    for i in range(12):
        nid = f"c-{i}"
        text = ("word " * per) + str(i)
        nodes[nid] = DagNode(
            id=nid,
            kind="chunk",
            depth=0,
            status="completed",
            output_summary=text,
            token_estimate=per,
        )
        deps.append(nid)
    parent = DagNode(
        id="region-1",
        kind="regional",
        depth=1,
        dep_ids=list(deps),
        status="pending",
        input_text="\n\n".join(nodes[d].output_summary for d in deps),
        token_estimate=per * 12,
    )
    nodes[parent.id] = parent
    inserted = insert_overflow_layer(nodes, parent, fan_in=3)
    assert inserted, "expected intermediate nodes when over budget"
    assert parent.dep_ids == inserted
    for iid in inserted:
        assert nodes[iid].kind in ("regional", "chapter")
        assert nodes[iid].status == "pending"


def test_ensure_prompt_budget_idempotent_when_small():
    nodes = {
        "a": DagNode(id="a", kind="chunk", depth=0, status="completed", output_summary="hi", token_estimate=1),
        "r": DagNode(id="r", kind="regional", depth=1, dep_ids=["a"], status="pending", input_text="hi", token_estimate=1),
    }
    ensure_prompt_budget(nodes, "r")
    assert nodes["r"].dep_ids == ["a"]


def test_ensure_prompt_budget_banned_outside_planning():
    """After planning, over-budget ensure_prompt_budget must fail hard (frozen DAG)."""
    from src.core.pipeline_dag import context_token_budget

    budget = context_token_budget()
    huge = "word " * (budget + 200)
    nodes = {
        "a": DagNode(
            id="a",
            kind="chunk",
            depth=0,
            status="completed",
            output_summary=huge,
            token_estimate=budget + 200,
        ),
        "r": DagNode(
            id="r",
            kind="regional",
            depth=1,
            dep_ids=["a"],
            status="pending",
            input_text=huge,
            token_estimate=budget + 200,
        ),
    }
    allow_planning_overflow(False)
    try:
        ensure_prompt_budget(nodes, "r")
        assert False, "expected RuntimeError when overflow banned"
    except RuntimeError as e:
        assert "refused after planning" in str(e) or "frozen" in str(e).lower()


def test_carbon_rollups_and_critical_path():
    nodes = {
        "a": DagNode(id="a", kind="chunk", depth=0, status="completed", carbon_estimate_g=0.1, latency_ms=100, assigned_model="m1", worker_id="w1"),
        "b": DagNode(id="b", kind="regional", depth=1, dep_ids=["a"], status="completed", carbon_estimate_g=0.2, latency_ms=200, assigned_model="m2", worker_id="w1"),
    }
    roll = carbon_rollups(nodes)
    assert roll["total_carbon_g"] == 0.3
    assert "m1" in roll["by_model"]
    assert critical_path_ms(nodes) == 300.0
    mets = perf_metrics(nodes, wall_ms=250.0, workers=2, api_calls=2, sequential_baseline_ms=300.0)
    assert mets["speedup_vs_sequential"] > 1.0
    assert "critical_path_ms" in mets


def test_critical_path_handles_cycles_without_recursion_error():
    """Regression: self/cyclic dep_ids must not raise RecursionError."""
    nodes = {
        "a": DagNode(id="a", kind="regional", depth=1, dep_ids=["b"], status="completed", latency_ms=10),
        "b": DagNode(id="b", kind="regional", depth=1, dep_ids=["a"], status="completed", latency_ms=20),
        "c": DagNode(id="c", kind="chapter", depth=2, dep_ids=["c"], status="completed", latency_ms=5),
    }
    cp = critical_path_ms(nodes)
    assert cp >= 0.0
    mets = perf_metrics(nodes, wall_ms=100.0, workers=1)
    assert mets["critical_path_ms"] >= 0.0


def test_overflow_reinsert_does_not_create_self_cycle():
    """Re-inserting overflow under the same parent must use unique ids (no self-deps)."""
    from src.core.pipeline_dag import context_token_budget

    budget = context_token_budget()
    per = max(500, (budget // 4) + 200)
    nodes = {}
    deps = []
    for i in range(12):
        nid = f"c-{i}"
        text = ("word " * per) + str(i)
        nodes[nid] = DagNode(
            id=nid,
            kind="chunk",
            depth=0,
            status="completed",
            output_summary=text,
            token_estimate=per,
        )
        deps.append(nid)
    parent = DagNode(
        id="region-1",
        kind="regional",
        depth=1,
        dep_ids=list(deps),
        status="pending",
        input_text="\n\n".join(nodes[d].output_summary for d in deps),
        token_estimate=per * 12,
    )
    nodes[parent.id] = parent
    first = insert_overflow_layer(nodes, parent, fan_in=3)
    assert first
    # Force another insert as if budget still exceeded (parent deps are intermediates)
    # Parent now depends on overflow nodes — a second insert must not self-loop.
    parent.token_estimate = budget + 1
    parent.input_text = "x" * (budget * 5)
    for iid in list(parent.dep_ids):
        nodes[iid].token_estimate = budget + 1
        nodes[iid].input_text = "y" * (budget * 5)
    second = insert_overflow_layer(nodes, parent, fan_in=2)
    assert second
    assert set(first).isdisjoint(set(second)), "overflow ids must be unique across inserts"
    for nid, n in nodes.items():
        assert nid not in (n.dep_ids or []), f"self-cycle on {nid}"
    # Budget helper must not spin forever / create cycles
    allow_planning_overflow(True)
    try:
        ensure_prompt_budget(nodes, parent.id)
    finally:
        allow_planning_overflow(False)
    for nid, n in nodes.items():
        assert nid not in (n.dep_ids or []), f"self-cycle after ensure on {nid}"
    assert critical_path_ms(nodes) >= 0.0


def test_ensure_prompt_budget_does_not_rebloat_from_pending_child_inputs():
    """Pending non-chunk deps must not be counted as full input_text for parent budget."""
    from src.chunking.service import estimate_tokens as _et
    from src.core.pipeline_dag import context_token_budget, estimate_compile_prompt_tokens

    budget = context_token_budget()
    huge = "word " * (budget + 500)
    nodes = {
        "c0": DagNode(
            id="c0",
            kind="chunk",
            depth=0,
            status="completed",
            output_summary="short summary zero",
            token_estimate=10,
        ),
        "ovf": DagNode(
            id="ovf",
            kind="regional",
            depth=1,
            dep_ids=["c0"],
            status="pending",
            input_text=huge,
            token_estimate=_et(huge),
        ),
        "parent": DagNode(
            id="parent",
            kind="chapter",
            depth=2,
            dep_ids=["ovf"],
            status="pending",
            input_text="",
            token_estimate=0,
        ),
    }
    est, _ = estimate_compile_prompt_tokens(nodes, nodes["parent"])
    assert est <= budget, f"pending child must be capped, got est={est} budget={budget}"
    allow_planning_overflow(True)
    try:
        inserted = ensure_prompt_budget(nodes, "parent")
    finally:
        allow_planning_overflow(False)
    assert not inserted, "must not overflow parent when only pending intermediate deps"
