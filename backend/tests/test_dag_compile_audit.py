"""Audit helpers: overflow vs baseline counts; critical-path timer."""
from __future__ import annotations

from src.core.pipeline_dag import DagNode, dag_progress_snapshot
from src.perf.critical_path import CriticalPath, dag_audit_reset, dag_audit_get


def test_snapshot_separates_overflow_regionals():
    nodes = {
        "chunk-0": DagNode(id="chunk-0", kind="chunk", depth=0, status="completed"),
        "region-a": DagNode(id="region-a", kind="regional", depth=1, status="pending"),
        "region-b": DagNode(id="region-b", kind="regional", depth=1, status="pending"),
        "region-a-ovf-0-1": DagNode(
            id="region-a-ovf-0-1",
            kind="regional",
            depth=1,
            status="pending",
            section_path="overflow/region-a/0",
        ),
        "region-a-ovf-0-2": DagNode(
            id="region-a-ovf-0-2",
            kind="regional",
            depth=1,
            status="pending",
            section_path="overflow/region-a/0",
        ),
    }
    snap = dag_progress_snapshot(nodes)
    assert snap["regional"]["total"] == 4  # mixed UI total
    assert snap["regional_baseline"] == 2
    assert snap["regional_overflow"] == 2
    assert snap["overflow"]["regional"]["total"] == 2
    assert snap["baseline"]["regional"]["total"] == 2


def test_critical_path_records_steps():
    cp = CriticalPath("job-test", label="post_dag")
    with cp.step("a"):
        pass
    with cp.step("b"):
        pass
    meta = cp.as_meta()
    assert "a" in meta["post_dag_breakdown"]
    assert "b" in meta["post_dag_breakdown"]
    assert meta["post_dag_total_ms"] >= 0


def test_dag_audit_reset_tracks_active_job():
    dag_audit_reset("job-xyz")
    a = dag_audit_get("job-xyz")
    assert a["misleading_executive_msgs"] == 0
    assert a["submit_counts"] == {}
