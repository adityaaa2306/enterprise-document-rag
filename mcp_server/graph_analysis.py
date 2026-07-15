"""Centrality, communities, hotspots, and architecture health reports."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx

from mcp_server.graph_loader import GraphBundle, ensure_betweenness, get_bundle
from mcp_server.graph_queries import _public_node, resolve_node


def hotspots(*, top: int = 25, bundle: Optional[GraphBundle] = None) -> Dict[str, Any]:
    b = bundle or get_bundle()
    ensure_betweenness(b)

    by_degree = sorted(b.degree.items(), key=lambda x: -x[1])[:top]
    by_between = sorted(b.betweenness.items(), key=lambda x: -x[1])[:top]

    # Largest communities
    sizes = sorted(
        ((cid, len(ids)) for cid, ids in b.by_community.items()),
        key=lambda x: -x[1],
    )[:top]

    communities = []
    for cid, size in sizes:
        members = b.by_community[cid]
        # pick highest-degree member as representative
        rep = max(members, key=lambda nid: b.degree.get(nid, 0))
        files = sorted(
            {
                b.nodes[n].get("source_file")
                for n in members
                if b.nodes[n].get("source_file")
            }
        )[:12]
        communities.append(
            {
                "id": cid,
                "size": size,
                "representative": _public_node(b.nodes[rep]),
                "sample_files": files,
            }
        )

    central = []
    for nid, deg in by_degree[:15]:
        n = b.nodes[nid]
        if n.get("kind") in {"file", "module", "class", "code"} or n.get("file_type") == "code":
            central.append({**_public_node(n), "degree": deg, "betweenness": b.betweenness.get(nid, 0.0)})

    return {
        "highest_degree": [
            {**_public_node(b.nodes[nid]), "degree": deg} for nid, deg in by_degree
        ],
        "highest_betweenness": [
            {
                **_public_node(b.nodes[nid]),
                "betweenness": round(float(score), 6),
                "degree": b.degree.get(nid, 0),
            }
            for nid, score in by_between
        ],
        "largest_communities": communities,
        "central_components": central,
        "stats": {
            "nodes": b.node_count,
            "edges": b.edge_count,
            "communities": len(b.by_community),
            "load_ms": round(b.load_ms, 1),
        },
    }


def community(community_id: int, *, limit: int = 80, bundle: Optional[GraphBundle] = None) -> Dict[str, Any]:
    b = bundle or get_bundle()
    try:
        cid = int(community_id)
    except (TypeError, ValueError):
        return {"error": f"invalid community id: {community_id}"}

    members = b.by_community.get(cid) or []
    if not members:
        return {"error": f"community not found: {cid}", "id": cid}

    files: Set[str] = set()
    modules: Counter = Counter()
    kinds: Counter = Counter()
    nodes_out = []
    for nid in sorted(members, key=lambda x: -b.degree.get(x, 0))[:limit]:
        n = b.nodes[nid]
        nodes_out.append({**_public_node(n), "degree": b.degree.get(nid, 0)})
        if n.get("source_file"):
            files.add(n["source_file"])
            # module = first 2-3 path segments
            parts = n["source_file"].replace("\\", "/").split("/")
            if len(parts) >= 2:
                modules["/".join(parts[:2])] += 1
            elif parts:
                modules[parts[0]] += 1
        kinds[n.get("kind") or "unknown"] += 1

    top_labels = [x["label"] for x in nodes_out[:8] if x.get("label")]
    purpose = (
        f"Community {cid} ({len(members)} nodes) — kinds: "
        + ", ".join(f"{k}={v}" for k, v in kinds.most_common(6))
        + ". Anchors: "
        + ", ".join(str(t) for t in top_labels)
        + "."
    )
    return {
        "id": cid,
        "size": len(members),
        "purpose": purpose,
        "summary": purpose,
        "files": sorted(files)[:60],
        "major_modules": [{"module": m, "nodes": c} for m, c in modules.most_common(15)],
        "kind_breakdown": dict(kinds),
        "nodes": nodes_out,
    }


def architecture_map(
    *,
    focus: Optional[str] = None,
    depth: int = 2,
    limit: int = 40,
    bundle: Optional[GraphBundle] = None,
) -> Dict[str, Any]:
    """Return a Mermaid flowchart for a focused neighborhood or top hotspots."""
    b = bundle or get_bundle()
    edges: List[Tuple[str, str, str]] = []
    node_ids: Set[str] = set()

    if focus:
        seed = resolve_node(focus, b)
        if not seed:
            return {"error": f"focus not found: {focus}", "mermaid": ""}
        node_ids.add(seed)
        frontier = {seed}
        for _ in range(max(1, depth)):
            nxt = set()
            for cur in frontier:
                for _, v, data in b.graph.out_edges(cur, data=True):
                    nxt.add(v)
                    edges.append((cur, v, data.get("relation") or "related"))
                for u, _, data in b.graph.in_edges(cur, data=True):
                    nxt.add(u)
                    edges.append((u, cur, data.get("relation") or "related"))
            node_ids |= nxt
            frontier = nxt - node_ids
            if len(node_ids) >= limit:
                break
    else:
        # top-degree skeleton
        top = sorted(b.degree.items(), key=lambda x: -x[1])[: min(20, limit)]
        node_ids = {nid for nid, _ in top}
        for nid in list(node_ids):
            for _, v, data in list(b.graph.out_edges(nid, data=True))[:5]:
                if v in node_ids or len(node_ids) < limit:
                    node_ids.add(v)
                    edges.append((nid, v, data.get("relation") or "related"))

    def mid(nid: str) -> str:
        label = (b.nodes[nid].get("label") or nid)[:40]
        safe = "".join(c if c.isalnum() else "_" for c in nid)[:48]
        return f'{safe}["{label}"]'

    lines = ["graph LR"]
    seen_e = set()
    for u, v, rel in edges[:limit * 2]:
        if u not in node_ids or v not in node_ids:
            continue
        key = (u, v, rel)
        if key in seen_e:
            continue
        seen_e.add(key)
        lines.append(f"  {mid(u)} -->|{rel}| {mid(v)}")

    mermaid = "\n".join(lines)
    return {
        "focus": focus,
        "node_count": len(node_ids),
        "edge_count": len(seen_e),
        "mermaid": mermaid,
        "nodes": [_public_node(b.nodes[n]) for n in list(node_ids)[:limit]],
    }


def architecture_report(
    *,
    include: Optional[List[str]] = None,
    bundle: Optional[GraphBundle] = None,
) -> Dict[str, Any]:
    """Optional health report: cycles, dead-ish nodes, large communities, reuse."""
    b = bundle or get_bundle()
    wanted = set(include or [
        "dead_code",
        "circular_dependencies",
        "largest_communities",
        "most_reused",
        "hidden_coupling",
    ])
    report: Dict[str, Any] = {"stats": {"nodes": b.node_count, "edges": b.edge_count}}

    if "circular_dependencies" in wanted:
        # cycles on import/call subgraph only (bounded — simple_cycles can explode)
        sub = nx.DiGraph()
        for u, v, data in b.graph.edges(data=True):
            if (data.get("relation") or "") in {"imports", "imports_from", "calls", "uses"}:
                sub.add_edge(u, v)
        cycles = []
        # Prefer strongly connected components of size 2..12
        for comp in nx.strongly_connected_components(sub):
            if 2 <= len(comp) <= 12:
                cycles.append([b.nodes[n].get("label") or n for n in sorted(comp)[:12]])
            if len(cycles) >= 25:
                break
        report["circular_dependencies"] = cycles

    if "dead_code" in wanted:
        # low in-degree code nodes that are not entry-ish
        dead = []
        for nid, n in b.nodes.items():
            if n.get("file_type") != "code" and n.get("kind") not in {"function", "class", "module", "file"}:
                continue
            indeg = b.graph.in_degree(nid)
            outdeg = b.graph.out_degree(nid)
            if indeg == 0 and outdeg <= 1 and b.degree.get(nid, 0) <= 2:
                dead.append(_public_node(n))
            if len(dead) >= 40:
                break
        report["dead_code_candidates"] = dead

    if "largest_communities" in wanted:
        report["largest_communities"] = hotspots(top=10, bundle=b)["largest_communities"]

    if "most_reused" in wanted:
        # highest in-degree via imports/calls
        reuse: Counter = Counter()
        for u, v, data in b.graph.edges(data=True):
            if (data.get("relation") or "") in {"imports", "imports_from", "calls", "uses", "references"}:
                reuse[v] += 1
        report["most_reused_modules"] = [
            {**_public_node(b.nodes[nid]), "inbound_refs": cnt}
            for nid, cnt in reuse.most_common(25)
            if nid in b.nodes
        ]

    if "hidden_coupling" in wanted:
        # pairs with many parallel relation types / multi-edges
        pair_rels: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
        for u, v, data in b.graph.edges(data=True):
            pair_rels[(u, v)].add(data.get("relation") or "related")
        coupling = []
        for (u, v), rels in pair_rels.items():
            if len(rels) >= 3:
                coupling.append(
                    {
                        "from": b.nodes[u].get("label") or u,
                        "to": b.nodes[v].get("label") or v,
                        "relations": sorted(rels),
                    }
                )
            if len(coupling) >= 30:
                break
        report["hidden_coupling"] = coupling

    if "layer_violations" in wanted:
        # heuristic: frontend importing backend deep internals or vice versa
        violations = []
        for u, v, data in b.graph.edges(data=True):
            if (data.get("relation") or "") not in {"imports", "imports_from", "calls"}:
                continue
            su = (b.nodes[u].get("source_file") or "").lower()
            sv = (b.nodes[v].get("source_file") or "").lower()
            if su.startswith("frontend/") and "/backend/" in f"/{sv}" or su.startswith("backend/") and sv.startswith("frontend/"):
                violations.append(
                    {
                        "from": b.nodes[u].get("label"),
                        "to": b.nodes[v].get("label"),
                        "relation": data.get("relation"),
                        "from_file": su,
                        "to_file": sv,
                    }
                )
            if len(violations) >= 25:
                break
        report["layer_violations"] = violations

    return report
