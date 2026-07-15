"""
Monotonic result_json store — unit + concurrency stress tests.

Invariant: concurrent patches in any order never lose information;
final result is identical for the same multiset of patches when applied
through update_result (order-independent for commutative enrichments).
"""
from __future__ import annotations

import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List

import pytest

from src.core.result_state_store import (
    apply_monotonic_guards,
    get_revision,
    monotonic_deep_merge,
    update_result,
)
from src.db import jobs as job_store


@pytest.fixture(autouse=True)
def _isolate_job_cache(monkeypatch):
    """Keep tests off the durable DB; use process-local JOB_STATUSES only."""
    monkeypatch.setattr(job_store, "_db_enabled", lambda: False)
    job_store.JOB_STATUSES.clear()
    yield
    job_store.JOB_STATUSES.clear()


def test_merge_never_overwrites_with_zero_or_unknown():
    base = {
        "carbon_data": {
            "baseline_cost_gco2e": 100.0,
            "total_chunks": 46,
            "compute_location": "IN",
            "region_decision": {"selected_region_name": "India"},
        },
        "chunk_routing": [{"i": 1}, {"i": 2}],
        "processing_insights": {"document_type": "report"},
        "final_summary": "hello world",
        "summary_ready": True,
        "background": {"phase": "search_ready", "message": "Search Ready"},
    }
    patch = {
        "carbon_data": {
            "baseline_cost_gco2e": 0.0,
            "total_chunks": 0,
            "compute_location": "unknown",
            "operational_co2e_g": 12.5,
        },
        "chunk_routing": [],
        "processing_insights": {},
        "final_summary": "hi",
        "summary_ready": False,
        "background": {"phase": "queued", "message": "Background Indexing"},
        "metrics_ready": False,
    }
    merged = monotonic_deep_merge(base, patch)
    merged, blocked = apply_monotonic_guards(base, merged)
    assert merged["carbon_data"]["baseline_cost_gco2e"] == 100.0
    assert merged["carbon_data"]["total_chunks"] == 46
    assert merged["carbon_data"]["compute_location"] == "IN"
    assert merged["carbon_data"]["operational_co2e_g"] == 12.5
    assert len(merged["chunk_routing"]) == 2
    assert merged["processing_insights"]["document_type"] == "report"
    assert merged["final_summary"] == "hello world"
    assert merged["summary_ready"] is True
    assert merged["background"]["phase"] == "search_ready"
    # Merge itself refuses empty/zero overwrites; guards are a second line of defense.
    assert isinstance(blocked, list)


def test_update_result_is_monotonic_across_stub_then_rich_then_stub():
    jid = "job-mono-1"
    job_store.JOB_STATUSES[jid] = {"job_id": jid, "status": "complete"}

    update_result(
        jid,
        {
            "final_summary": "Summary text here",
            "summary_ready": True,
            "background": {"phase": "queued", "message": "Background Indexing"},
            "carbon_data": {
                "baseline_cost_gco2e": 0.0,
                "operational_co2e_g": 50.0,
                "total_chunks": 46,
            },
            "chunk_routing": [{"i": n} for n in range(10)],
            "processing_insights": {"document_type": "doc"},
        },
        source="test.deliver_summary",
    )
    update_result(
        jid,
        {
            "background": {"phase": "search_ready", "message": "Search Ready"},
            "metrics_ready": True,
            "search_ready": True,
            "carbon_data": {
                "baseline_cost_gco2e": 121.8,
                "carbon_saved_grams": 46.1,
                "local_grid_gco2_kwh": 642,
                "compute_location": "IN",
                "region_decision": {"selected_region_name": "India"},
                "grid_zone": "IN-WE",
            },
        },
        source="test.patch_carbon",
    )
    # Attacker: try to re-apply Summary Ready stub
    update_result(
        jid,
        {
            "background": {"phase": "queued", "message": "Background Indexing"},
            "carbon_data": {
                "baseline_cost_gco2e": 0.0,
                "operational_co2e_g": 50.0,
                "total_chunks": 0,
                "compute_location": "unknown",
            },
            "chunk_routing": [],
            "processing_insights": {},
            "metrics_ready": False,
            "search_ready": False,
        },
        source="test.stale_stub",
    )
    final = job_store.JOB_STATUSES[jid]["result"]
    assert final["carbon_data"]["baseline_cost_gco2e"] == 121.8
    assert final["carbon_data"]["region_decision"]["selected_region_name"] == "India"
    assert final["carbon_data"]["total_chunks"] == 46
    assert len(final["chunk_routing"]) == 10
    assert final["processing_insights"]["document_type"] == "doc"
    assert final["background"]["phase"] == "search_ready"
    assert final.get("metrics_ready") is True
    assert get_revision(final) >= 3


def _enrichment_patches() -> List[Dict[str, Any]]:
    return [
        {
            "final_summary": "A complete summary of the document content.",
            "summary_ready": True,
            "background": {"phase": "queued"},
            "carbon_data": {"operational_co2e_g": 10.0, "total_chunks": 5},
        },
        {
            "background": {"phase": "embeddings"},
            "processing_insights": {"document_type": "report", "confidence": 0.8},
        },
        {
            "chunk_routing": [{"i": 0}, {"i": 1}, {"i": 2}],
            "routing_distribution": {"light": 1, "medium": 2, "heavy": 0},
        },
        {
            "background": {"phase": "search_ready", "message": "Search Ready"},
            "metrics_ready": True,
            "search_ready": True,
            "carbon_data": {
                "baseline_cost_gco2e": 40.0,
                "carbon_saved_grams": 20.0,
                "local_grid_gco2_kwh": 500,
                "region_decision": {"selected_region_name": "India"},
                "compute_location": "IN",
            },
        },
        {
            "execution_plan": {"nodes": [1, 2, 3, 4]},
            "compile_meta": {"ok": True},
        },
        # Noise / regressive patches that must not win
        {"carbon_data": {"baseline_cost_gco2e": 0.0, "total_chunks": 0}},
        {"background": {"phase": "queued"}, "metrics_ready": False},
        {"chunk_routing": [], "processing_insights": {}},
        {"final_summary": "x"},
    ]


def test_concurrent_updates_never_lose_rich_fields():
    jid = "job-stress-1"
    job_store.JOB_STATUSES[jid] = {"job_id": jid, "status": "complete"}
    patches = _enrichment_patches()

    def apply_one(p: Dict[str, Any], idx: int) -> None:
        update_result(jid, p, source=f"stress.{idx}")

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(apply_one, p, i) for i, p in enumerate(patches)]
        for f in as_completed(futs):
            f.result()

    final = job_store.JOB_STATUSES[jid]["result"]
    assert final["carbon_data"]["baseline_cost_gco2e"] == 40.0
    assert final["carbon_data"]["region_decision"]["selected_region_name"] == "India"
    assert final["carbon_data"]["total_chunks"] == 5
    assert len(final["chunk_routing"]) >= 3
    assert final["processing_insights"]["document_type"] == "report"
    assert final["background"]["phase"] == "search_ready"
    assert final.get("metrics_ready") is True
    assert len(final["final_summary"]) > 5
    assert len(final["execution_plan"]["nodes"]) == 4


@pytest.mark.parametrize("seed", list(range(20)))
def test_randomized_order_same_terminal_richness(seed: int):
    """For many random orders, terminal richness invariants hold identically."""
    patches = _enrichment_patches()
    rng = random.Random(seed)
    order = list(patches)
    rng.shuffle(order)

    jid = f"job-order-{seed}"
    job_store.JOB_STATUSES[jid] = {"job_id": jid, "status": "complete"}
    for i, p in enumerate(order):
        update_result(jid, p, source=f"order.{seed}.{i}")

    final = job_store.JOB_STATUSES[jid]["result"]
    assert final["carbon_data"]["baseline_cost_gco2e"] == 40.0
    assert final["background"]["phase"] == "search_ready"
    assert final.get("metrics_ready") is True
    assert final["processing_insights"]["document_type"] == "report"
    assert len(final["chunk_routing"]) >= 3


def _assert_rich_terminal(final: Dict[str, Any]) -> None:
    assert final["carbon_data"]["baseline_cost_gco2e"] == 40.0
    assert final["carbon_data"]["region_decision"]["selected_region_name"] == "India"
    assert len(final["chunk_routing"]) >= 3
    assert final["processing_insights"]["document_type"] == "report"
    assert final["background"]["phase"] == "search_ready"
    assert final.get("metrics_ready") is True
    assert len(final["final_summary"]) > 5


def test_stress_10000_random_update_orders_invariant():
    """
    10,000 randomized update orders.

    Invariant: never rich→stub; baseline/region/routing/PI always retained once set;
    terminal richness is identical across orders.
    """
    patches = _enrichment_patches()
    for n in range(10_000):
        rng = random.Random(n)
        order = list(patches)
        rng.shuffle(order)
        jid = f"job-10k-{n}"
        job_store.JOB_STATUSES[jid] = {"job_id": jid, "status": "complete"}
        for i, p in enumerate(order):
            update_result(jid, p, source=f"tenk.{n}.{i}")
        _assert_rich_terminal(job_store.JOB_STATUSES[jid]["result"])
        # Drop finished jobs to keep memory bounded
        del job_store.JOB_STATUSES[jid]


def test_concurrent_writer_roles_never_lose_updates():
    """
    Simulate summary / carbon / background / progress / status-heal writers
    racing on one job.
    """
    jid = "job-roles"
    job_store.JOB_STATUSES[jid] = {"job_id": jid, "status": "processing", "progress": 10.0}
    barrier = threading.Barrier(5)
    errors: List[BaseException] = []

    def summary_writer():
        try:
            barrier.wait(timeout=10)
            update_result(
                jid,
                {
                    "final_summary": "A complete summary of the document content.",
                    "summary_ready": True,
                    "background": {"phase": "queued", "message": "Background Indexing"},
                    "carbon_data": {"operational_co2e_g": 10.0, "total_chunks": 5},
                    "chunk_routing": [{"i": 0}, {"i": 1}, {"i": 2}],
                    "processing_insights": {"document_type": "report"},
                    "execution_plan": {"nodes": [1, 2, 3, 4]},
                },
                source="role.summary",
            )
            job_store.upsert_job(jid, status="complete", progress=91.0, message="Summary Ready")
        except BaseException as e:
            errors.append(e)

    def carbon_writer():
        try:
            barrier.wait(timeout=10)
            update_result(
                jid,
                {
                    "metrics_ready": True,
                    "search_ready": True,
                    "carbon_data": {
                        "baseline_cost_gco2e": 40.0,
                        "carbon_saved_grams": 20.0,
                        "local_grid_gco2_kwh": 500,
                        "region_decision": {"selected_region_name": "India"},
                        "compute_location": "IN",
                    },
                    "background": {"phase": "search_ready", "message": "Search Ready"},
                },
                source="role.carbon",
            )
        except BaseException as e:
            errors.append(e)

    def background_writer():
        try:
            barrier.wait(timeout=10)
            for phase in ("embeddings", "carbon", "search_ready"):
                update_result(
                    jid,
                    {"background": {"phase": phase, "message": phase}},
                    source=f"role.bg.{phase}",
                )
        except BaseException as e:
            errors.append(e)

    def progress_writer():
        try:
            barrier.wait(timeout=10)
            for p in (50.0, 75.0, 91.0, 100.0):
                job_store.upsert_job(jid, progress=p, message=f"progress {p}")
        except BaseException as e:
            errors.append(e)

    def status_heal_writer():
        try:
            barrier.wait(timeout=10)
            for _ in range(20):
                job_store.upsert_job(
                    jid,
                    status="complete",
                    progress=100.0,
                    message="Summary Ready · Finishing analytics…",
                )
                # Regressive stub attempt (must not win)
                update_result(
                    jid,
                    {
                        "carbon_data": {"baseline_cost_gco2e": 0.0, "total_chunks": 0},
                        "chunk_routing": [],
                        "metrics_ready": False,
                        "background": {"phase": "queued"},
                    },
                    source="role.heal_stub",
                )
        except BaseException as e:
            errors.append(e)

    threads = [
        threading.Thread(target=summary_writer),
        threading.Thread(target=carbon_writer),
        threading.Thread(target=background_writer),
        threading.Thread(target=progress_writer),
        threading.Thread(target=status_heal_writer),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors, errors
    _assert_rich_terminal(job_store.JOB_STATUSES[jid]["result"])
    assert float(job_store.JOB_STATUSES[jid].get("progress") or 0) >= 91.0


def test_upsert_without_result_does_not_clobber_result(monkeypatch):
    jid = "job-no-clobber"
    job_store.JOB_STATUSES[jid] = {"job_id": jid, "status": "complete"}
    update_result(
        jid,
        {
            "final_summary": "keep me",
            "summary_ready": True,
            "carbon_data": {"baseline_cost_gco2e": 99.0, "total_chunks": 10},
            "background": {"phase": "search_ready"},
            "metrics_ready": True,
        },
        source="setup",
    )
    # Progress/message only
    job_store.upsert_job(jid, message="Search Ready", progress=100.0)
    # Stale heal-style status write without result
    job_store.upsert_job(jid, status="complete", message="Summary Ready · Finishing analytics…")
    final = job_store.JOB_STATUSES[jid]["result"]
    assert final["carbon_data"]["baseline_cost_gco2e"] == 99.0
    assert final["background"]["phase"] == "search_ready"


def test_legacy_upsert_result_routes_through_store():
    jid = "job-legacy"
    job_store.JOB_STATUSES[jid] = {"job_id": jid, "status": "complete"}
    job_store.upsert_job(
        jid,
        result={
            "final_summary": "first",
            "summary_ready": True,
            "carbon_data": {"baseline_cost_gco2e": 10.0, "total_chunks": 3},
            "background": {"phase": "search_ready"},
        },
        result_source="test.legacy",
    )
    job_store.upsert_job(
        jid,
        result={
            "final_summary": "x",
            "carbon_data": {"baseline_cost_gco2e": 0.0, "total_chunks": 0},
            "background": {"phase": "queued"},
        },
        result_source="test.legacy_stub",
    )
    final = job_store.JOB_STATUSES[jid]["result"]
    assert final["carbon_data"]["baseline_cost_gco2e"] == 10.0
    assert final["background"]["phase"] == "search_ready"
    assert get_revision(final) >= 2
