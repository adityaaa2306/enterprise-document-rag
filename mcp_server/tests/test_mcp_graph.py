"""Tests for Architecture Intelligence graph engine."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from mcp_server.graph_analysis import architecture_map, community, hotspots
from mcp_server.graph_loader import DEFAULT_GRAPH_PATH, get_bundle, load_graph
from mcp_server.graph_queries import (
    architecture,
    dependencies,
    explain_flow,
    impact,
    locate,
    module_summary,
    neighbors,
    search_nodes,
    shortest_path,
)

pytestmark = pytest.mark.skipif(
    not DEFAULT_GRAPH_PATH.exists(),
    reason="graphify-out/graph.json missing",
)


@pytest.fixture(scope="module")
def bundle():
    return get_bundle()


def test_load_once(bundle):
    assert bundle.node_count > 100
    assert bundle.edge_count > 100
    assert bundle.load_ms > 0


def test_search_nodes_fuzzy(bundle):
    hits = search_nodes("carbon", limit=10, bundle=bundle)
    assert hits
    labels = " ".join((h.get("label") or "").lower() for h in hits)
    assert "carbon" in labels or any("carbon" in (h.get("id") or "").lower() for h in hits)
    assert "score" in hits[0]
    assert "summary" in hits[0]


def test_search_kind_filter(bundle):
    hits = search_nodes("orchestrator", limit=15, kinds=["file", "module", "class"], bundle=bundle)
    assert isinstance(hits, list)


def test_neighbors(bundle):
    seeds = search_nodes("orchestrator", limit=3, bundle=bundle)
    assert seeds
    nb = neighbors(seeds[0]["id"], limit=20, bundle=bundle)
    assert nb.get("node")
    assert "neighbors" in nb


def test_shortest_path_and_flow(bundle):
    a = search_nodes("chunk", limit=5, bundle=bundle)
    b = search_nodes("router", limit=5, bundle=bundle)
    if not a or not b:
        pytest.skip("insufficient seeds")
    path = shortest_path(a[0]["label"], b[0]["label"], bundle=bundle)
    assert "path" in path
    flow = explain_flow(a[0]["label"], b[0]["label"], bundle=bundle)
    assert "explanation" in flow or flow.get("error")


def test_dependencies_and_reverse(bundle):
    seeds = search_nodes("orchestrator", limit=3, bundle=bundle)
    assert seeds
    deps = dependencies(seeds[0]["id"], bundle=bundle)
    assert "imports" in deps
    from mcp_server.graph_queries import reverse_dependencies

    rev = reverse_dependencies(seeds[0]["id"], limit=20, bundle=bundle)
    assert "dependents" in rev


def test_module_summary_and_locate(bundle):
    ms = module_summary("chunk_router", bundle=bundle)
    assert "important_files" in ms or "error" in ms
    loc = locate("carbon accounting", limit=10, bundle=bundle)
    assert "files" in loc
    assert "nodes" in loc


def test_architecture_qa(bundle):
    t0 = time.perf_counter()
    ans = architecture("How does carbon accounting work?", limit=8, bundle=bundle)
    ms = (time.perf_counter() - t0) * 1000
    assert ans.get("explanation")
    assert ans.get("nodes")
    # Warm path should be snappy; allow headroom on cold CI
    assert ms < 5000


def test_hotspots_and_community(bundle):
    hs = hotspots(top=10, bundle=bundle)
    assert hs["highest_degree"]
    assert hs["largest_communities"]
    cid = hs["largest_communities"][0]["id"]
    c = community(cid, limit=20, bundle=bundle)
    assert c.get("files") is not None
    assert c.get("summary") or c.get("purpose")


def test_impact_and_map(bundle):
    seeds = search_nodes("carbon", limit=3, bundle=bundle)
    assert seeds
    imp = impact(seeds[0]["id"], depth=2, limit=30, bundle=bundle)
    assert "affected_files" in imp
    m = architecture_map(focus=seeds[0]["label"], depth=1, limit=20, bundle=bundle)
    assert "mermaid" in m
    assert m["mermaid"].startswith("graph")


def test_reload_independent():
    b1 = load_graph(DEFAULT_GRAPH_PATH)
    b2 = load_graph(DEFAULT_GRAPH_PATH)
    assert b1.node_count == b2.node_count
