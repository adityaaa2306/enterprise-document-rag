"""Frozen DAG / planning / repair queue regression tests."""
from __future__ import annotations

from src.core.pipeline_dag import DagNode, dag_progress_snapshot
from src.core.planning import (
    ExecutionPlan,
    assert_dag_immutable,
    fingerprint_topology,
    plan_compile_hierarchy,
)
from src.core.repair_queue import RepairQueue, run_repair_tasks


class _Chunk:
    def __init__(self, content: str, parent_id: str = "sec-1", index: int = 0):
        self.content = content
        self.parent_id = parent_id
        self.index = index
        self.type = "NarrativeText"
        self.metadata = {}


def test_plan_freezes_and_fingerprint_stable():
    chunks = [_Chunk(f"Paragraph {i} about carbon routing and RAG systems. " * 20, index=i) for i in range(4)]
    summaries = [c.content[:200] for c in chunks]
    nodes = {
        f"chunk-{i}": DagNode(
            id=f"chunk-{i}",
            kind="chunk",
            depth=0,
            status="completed",
            output_summary=summaries[i],
            input_text=chunks[i].content,
            chunk_index=i,
        )
        for i in range(4)
    }
    planned, plan = plan_compile_hierarchy(
        nodes,
        chunks,
        summaries,
        job_id="job-plan-1",
        fan_in=2,
        max_depth=6,
        skip_regional_below=0,
        compile_workers=2,
    )
    assert plan.frozen is True
    assert plan.node_count == len(planned)
    assert plan.fingerprint == fingerprint_topology(planned)
    before = len(planned)
    assert_dag_immutable(planned, plan, phase="test")
    # Mutating status is OK
    for n in planned.values():
        if n.kind != "chunk":
            n.status = "completed"
            n.output_summary = "ok"
            break
    assert_dag_immutable(planned, plan, phase="after_status")
    assert len(planned) == before
    # ensure_prompt_budget must be banned after plan returns
    from src.core.pipeline_dag import ensure_prompt_budget, planning_overflow_allowed

    assert planning_overflow_allowed() is False


def test_planner_ema_converges():
    from src.core.planning import planner_ema_snapshot, update_planner_ema

    before = planner_ema_snapshot()
    after = update_planner_ema(
        {
            "runtime_sec": 120.0,
            "carbon_g": 2.0,
            "api_calls": 40,
            "hierarchy_depth": 4,
            "sec_per_compile_node": 10.0,
            "carbon_per_compile_node": 0.05,
        }
    )
    assert after["runtime_sec"] != before["runtime_sec"] or after["api_calls"] != before["api_calls"]


def test_assert_dag_immutable_detects_new_node():
    nodes = {
        "chunk-0": DagNode(id="chunk-0", kind="chunk", depth=0, status="completed"),
        "region-a": DagNode(
            id="region-a", kind="regional", depth=1, status="pending", dep_ids=["chunk-0"]
        ),
    }
    plan = ExecutionPlan(
        job_id="j",
        frozen=True,
        fingerprint=fingerprint_topology(nodes),
        node_ids=sorted(nodes.keys()),
        node_count=len(nodes),
        topology={
            "chunk-0": {"id": "chunk-0", "kind": "chunk", "depth": 0, "dep_ids": [], "children_ids": [], "section_path": ""},
            "region-a": {
                "id": "region-a",
                "kind": "regional",
                "depth": 1,
                "dep_ids": ["chunk-0"],
                "children_ids": [],
                "section_path": "",
            },
        },
    )
    nodes["region-a-ovf-0-1"] = DagNode(
        id="region-a-ovf-0-1", kind="regional", depth=1, status="pending"
    )
    try:
        assert_dag_immutable(nodes, plan, phase="test_overflow")
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "added" in str(e) or "mutated" in str(e).lower()


def test_repair_queue_does_not_require_dag_mutation():
    rq = RepairQueue("job-r")
    rq.enqueue("n1", "weak")
    rq.enqueue("n2", "weak")
    seen = []

    def _fn(nid: str) -> bool:
        seen.append(nid)
        return True

    report = run_repair_tasks(rq, recompute_fn=_fn, max_tasks=2)
    assert report["completed"] == 2
    assert set(seen) == {"n1", "n2"}


def test_snapshot_overflow_fields_present():
    nodes = {
        "r1": DagNode(id="r1", kind="regional", depth=1, status="pending"),
        "r1-ovf-0-1": DagNode(
            id="r1-ovf-0-1",
            kind="regional",
            depth=1,
            status="pending",
            section_path="overflow/r1/0",
        ),
    }
    snap = dag_progress_snapshot(nodes)
    assert snap["regional_baseline"] == 1
    assert snap["regional_overflow"] == 1
