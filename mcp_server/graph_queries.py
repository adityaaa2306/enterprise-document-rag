"""Graph query engine — search, neighbors, paths, deps, architecture Q&A."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import networkx as nx
from rapidfuzz import fuzz

from mcp_server.graph_loader import GraphBundle, _norm, get_bundle

KIND_ALIASES = {
    "file": {"file", "code"},
    "class": {"class"},
    "function": {"function"},
    "module": {"module"},
    "document": {"document"},
    "readme": {"readme"},
    "image": {"image"},
    "paper": {"paper"},
    "concept": {"concept"},
    "rationale": {"rationale"},
}

DEP_RELATIONS = {
    "imports": {"imports", "imports_from", "re_exports"},
    "calls": {"calls", "indirect_call", "method", "uses"},
    "inherits": {"inherits", "extends"},
    "references": {"references", "defines", "conceptually_related_to", "semantically_similar_to"},
    "documents": {"rationale_for", "contains"},
    "contains": {"contains"},
}


def _merge_hits(primary: List[Dict[str, Any]], extra: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = {h["id"] for h in primary}
    out = list(primary)
    for h in extra:
        if h["id"] not in seen:
            seen.add(h["id"])
            out.append(h)
    return out


def _public_node(n: Dict[str, Any], *, score: Optional[float] = None) -> Dict[str, Any]:
    out = {
        "id": n.get("id"),
        "label": n.get("label"),
        "type": n.get("file_type"),
        "kind": n.get("kind"),
        "source_file": n.get("source_file"),
        "community": n.get("community"),
        "summary": _node_summary(n),
    }
    if score is not None:
        out["score"] = round(float(score), 3)
    return out


def _node_summary(n: Dict[str, Any]) -> str:
    bits = []
    if n.get("kind"):
        bits.append(str(n["kind"]))
    if n.get("source_file"):
        bits.append(str(n["source_file"]))
    if n.get("source_location"):
        bits.append(str(n["source_location"]))
    return " · ".join(bits) if bits else (n.get("label") or n.get("id") or "")


def resolve_node(query: str, bundle: Optional[GraphBundle] = None) -> Optional[str]:
    """Resolve a label/id/fuzzy string to a single best node id."""
    hits = search_nodes(query, limit=5, bundle=bundle)
    if not hits:
        return None
    return hits[0]["id"]


def search_nodes(
    query: str,
    *,
    limit: int = 20,
    kinds: Optional[Sequence[str]] = None,
    file_contains: Optional[str] = None,
    bundle: Optional[GraphBundle] = None,
) -> List[Dict[str, Any]]:
    b = bundle or get_bundle()
    q = (query or "").strip()
    if not q:
        return []
    qn = _norm(q)
    kind_set: Optional[Set[str]] = None
    if kinds:
        kind_set = set()
        for k in kinds:
            kind_set |= KIND_ALIASES.get(k.lower(), {k.lower()})

    scored: List[Tuple[float, str]] = []
    # Exact / prefix index hits first
    candidates: Set[str] = set()
    if q.lower() in b.by_label:
        candidates.update(b.by_label[q.lower()])
    if qn in b.by_norm_label:
        candidates.update(b.by_norm_label[qn])
    # id exact
    if q in b.nodes:
        candidates.add(q)
    # token overlap scan (bounded)
    tokens = [t for t in qn.split() if len(t) > 1]
    for nid, n in b.nodes.items():
        if kind_set and (n.get("kind") or "") not in kind_set and (n.get("file_type") or "") not in kind_set:
            continue
        if file_contains:
            sf = (n.get("source_file") or "").lower()
            if file_contains.lower() not in sf:
                continue
        label = n.get("label") or ""
        nl = n.get("norm_label") or _norm(label)
        # cheap prefilter
        if tokens and not any(t in nl or t in nid.lower() or t in (n.get("source_file") or "").lower() for t in tokens):
            if nid not in candidates:
                continue
        candidates.add(nid)

    # If still tiny, broaden: fuzzy against all labels (expensive but capped)
    if len(candidates) < 8:
        for nid, n in b.nodes.items():
            label = n.get("label") or ""
            score = fuzz.partial_ratio(qn, _norm(label))
            if score >= 70:
                candidates.add(nid)

    for nid in candidates:
        n = b.nodes[nid]
        if kind_set and (n.get("kind") or "") not in kind_set and (n.get("file_type") or "") not in kind_set:
            continue
        if file_contains and file_contains.lower() not in (n.get("source_file") or "").lower():
            continue
        label = n.get("label") or ""
        nl = n.get("norm_label") or _norm(label)
        score = float(fuzz.WRatio(qn, nl))
        if qn == nl or q.lower() == label.lower():
            score = 100.0
        elif nid == q or nid.lower() == q.lower():
            score = 99.0
        else:
            # boost degree / path presence
            score += min(10.0, 0.3 * b.degree.get(nid, 0))
            if tokens:
                hit = sum(1 for t in tokens if t in nl or t in nid.lower())
                score += 5.0 * hit
            # Prefer compact code symbols over long doc/image captions
            if len(label) > 80:
                score -= 15.0
            elif len(label) > 40:
                score -= 5.0
            kind = n.get("kind") or ""
            if kind in {"class", "function", "module", "file", "code"}:
                score += 8.0
            elif kind in {"document", "paper", "image", "concept"}:
                score -= 3.0
        scored.append((score, nid))

    scored.sort(key=lambda x: (-x[0], x[1]))
    out = []
    seen = set()
    for score, nid in scored:
        if nid in seen:
            continue
        seen.add(nid)
        out.append(_public_node(b.nodes[nid], score=score))
        if len(out) >= limit:
            break
    return out


def neighbors(
    node: str,
    *,
    relation: Optional[str] = None,
    direction: str = "both",
    limit: int = 50,
    bundle: Optional[GraphBundle] = None,
) -> Dict[str, Any]:
    b = bundle or get_bundle()
    nid = resolve_node(node, b) or node
    if nid not in b.nodes:
        return {"error": f"node not found: {node}", "node": None, "neighbors": []}

    rel_filter: Optional[Set[str]] = None
    if relation:
        rel_filter = DEP_RELATIONS.get(relation.lower(), {relation.lower()})

    results = []
    seen = set()

    def add_edge(u: str, v: str, data: Dict[str, Any], direction_label: str) -> None:
        key = (u, v, data.get("relation"), direction_label)
        if key in seen:
            return
        seen.add(key)
        if rel_filter and (data.get("relation") or "") not in rel_filter:
            return
        other = v if direction_label == "out" else u
        if other == nid:
            other = u if direction_label == "out" else v
        results.append(
            {
                **_public_node(b.nodes[other]),
                "relation": data.get("relation"),
                "direction": direction_label,
                "weight": data.get("weight"),
            }
        )

    if direction in ("out", "both"):
        for _, v, data in b.graph.out_edges(nid, data=True):
            add_edge(nid, v, data, "out")
    if direction in ("in", "both"):
        for u, _, data in b.graph.in_edges(nid, data=True):
            add_edge(u, nid, data, "in")

    results.sort(key=lambda r: (-(b.degree.get(r["id"], 0)), r.get("label") or ""))
    return {
        "node": _public_node(b.nodes[nid]),
        "count": len(results[:limit]),
        "neighbors": results[:limit],
    }


def shortest_path(
    node_a: str,
    node_b: str,
    *,
    bundle: Optional[GraphBundle] = None,
) -> Dict[str, Any]:
    b = bundle or get_bundle()
    a = resolve_node(node_a, b) or node_a
    c = resolve_node(node_b, b) or node_b
    if a not in b.nodes or c not in b.nodes:
        return {"error": "one or both nodes not found", "path": []}
    und = b.graph.to_undirected()
    try:
        path = nx.shortest_path(und, a, c)
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return {
            "error": "no path",
            "from": _public_node(b.nodes[a]),
            "to": _public_node(b.nodes[c]),
            "path": [],
            "hops": None,
        }
    steps = [_public_node(b.nodes[n]) for n in path]
    return {
        "from": steps[0],
        "to": steps[-1],
        "hops": len(path) - 1,
        "path": steps,
        "path_labels": [s["label"] for s in steps],
    }


def dependencies(node: str, bundle: Optional[GraphBundle] = None) -> Dict[str, Any]:
    b = bundle or get_bundle()
    nid = resolve_node(node, b) or node
    if nid not in b.nodes:
        return {"error": f"node not found: {node}"}

    buckets: Dict[str, List[Dict[str, Any]]] = {
        "imports": [],
        "calls": [],
        "inherits": [],
        "references": [],
        "documents": [],
    }
    for _, v, data in b.graph.out_edges(nid, data=True):
        rel = (data.get("relation") or "").lower()
        item = {**_public_node(b.nodes[v]), "relation": rel}
        placed = False
        for bucket, rels in DEP_RELATIONS.items():
            if bucket == "contains":
                continue
            if rel in rels and bucket in buckets:
                buckets[bucket].append(item)
                placed = True
                break
        if not placed:
            buckets["references"].append(item)
    return {"node": _public_node(b.nodes[nid]), **buckets}


def reverse_dependencies(node: str, *, limit: int = 80, bundle: Optional[GraphBundle] = None) -> Dict[str, Any]:
    b = bundle or get_bundle()
    nid = resolve_node(node, b) or node
    if nid not in b.nodes:
        return {"error": f"node not found: {node}"}
    items = []
    for u, _, data in b.graph.in_edges(nid, data=True):
        items.append({**_public_node(b.nodes[u]), "relation": data.get("relation")})
    items.sort(key=lambda r: (-b.degree.get(r["id"], 0), r.get("label") or ""))
    return {
        "node": _public_node(b.nodes[nid]),
        "dependents": items[:limit],
        "count": len(items),
    }


def impact(node: str, *, depth: int = 2, limit: int = 60, bundle: Optional[GraphBundle] = None) -> Dict[str, Any]:
    """Files/nodes likely affected if this node changes (reverse BFS)."""
    b = bundle or get_bundle()
    nid = resolve_node(node, b) or node
    if nid not in b.nodes:
        return {"error": f"node not found: {node}"}

    # Prefer reverse edges (who uses me); fall back to undirected BFS
    affected: Dict[str, int] = {}
    frontier = {nid}
    visited = {nid}
    for d in range(1, max(1, depth) + 1):
        nxt = set()
        for cur in frontier:
            for pred in b.graph.predecessors(cur):
                if pred not in visited:
                    visited.add(pred)
                    nxt.add(pred)
                    affected[pred] = d
            # also outbound contains children for file/module edits
            for succ in b.graph.successors(cur):
                edge_data = b.graph.get_edge_data(cur, succ) or {}
                rels = [d.get("relation") for d in edge_data.values()]
                if any(r in {"contains", "defines", "method"} for r in rels):
                    if succ not in visited:
                        visited.add(succ)
                        nxt.add(succ)
                        affected.setdefault(succ, d)
        frontier = nxt
        if not frontier:
            break

    files: Dict[str, int] = {}
    nodes_out = []
    for aid, dist in sorted(affected.items(), key=lambda x: (x[1], -b.degree.get(x[0], 0))):
        n = b.nodes[aid]
        nodes_out.append({**_public_node(n), "distance": dist})
        sf = n.get("source_file")
        if sf:
            files[sf] = min(files.get(sf, dist), dist)
        if len(nodes_out) >= limit:
            break

    file_list = [{"file": f, "distance": d} for f, d in sorted(files.items(), key=lambda x: (x[1], x[0]))]
    return {
        "node": _public_node(b.nodes[nid]),
        "affected_nodes": nodes_out,
        "affected_files": file_list[:limit],
        "depth": depth,
    }


def locate(feature: str, *, limit: int = 25, bundle: Optional[GraphBundle] = None) -> Dict[str, Any]:
    hits = search_nodes(feature, limit=limit, bundle=bundle)
    files = []
    seen = set()
    for h in hits:
        sf = h.get("source_file")
        if sf and sf not in seen:
            seen.add(sf)
            files.append({"file": sf, "via_node": h["label"], "score": h.get("score"), "kind": h.get("kind")})
    # also pull README/docs from related neighbors of top hits
    b = bundle or get_bundle()
    for h in hits[:5]:
        nid = h["id"]
        for _, v, data in list(b.graph.out_edges(nid, data=True))[:20]:
            n = b.nodes[v]
            if n.get("kind") in {"readme", "document", "paper"} or (n.get("file_type") in {"document", "image"}):
                sf = n.get("source_file")
                if sf and sf not in seen:
                    seen.add(sf)
                    files.append({"file": sf, "via_node": n.get("label"), "score": h.get("score"), "kind": n.get("kind")})
    return {"query": feature, "nodes": hits, "files": files[:limit]}


def module_summary(module: str, bundle: Optional[GraphBundle] = None) -> Dict[str, Any]:
    b = bundle or get_bundle()
    hits = search_nodes(module, limit=15, bundle=b)
    if not hits:
        return {"error": f"module not found: {module}"}

    # Prefer node whose source_file path contains the query
    qn = _norm(module)
    seed = hits[0]["id"]
    for h in hits:
        sf = (h.get("source_file") or "").lower().replace("\\", "/")
        if qn.replace(" ", "/") in sf or qn.replace(" ", "_") in (h.get("id") or ""):
            seed = h["id"]
            break

    seed_n = b.nodes[seed]
    # Collect community + file cluster
    files: Set[str] = set()
    classes: List[str] = []
    functions: List[str] = []
    deps: Set[str] = set()
    users: Set[str] = set()

    related_ids = {seed}
    sf0 = seed_n.get("source_file") or ""
    if sf0:
        related_ids.update(b.by_file.get(sf0.lower(), []))
        # same directory
        parent = "/".join(sf0.split("/")[:-1])
        if parent:
            for nid, n in b.nodes.items():
                s = n.get("source_file") or ""
                if s.startswith(parent + "/") or s == sf0:
                    related_ids.add(nid)

    comm = seed_n.get("community")
    if comm is not None:
        related_ids.update(b.by_community.get(int(comm), [])[:80])

    for nid in related_ids:
        n = b.nodes[nid]
        if n.get("source_file"):
            files.add(n["source_file"])
        if n.get("kind") == "class":
            classes.append(n.get("label") or nid)
        if n.get("kind") == "function":
            functions.append(n.get("label") or nid)
        for _, v, data in b.graph.out_edges(nid, data=True):
            if data.get("relation") in {"imports", "imports_from", "calls", "uses"}:
                deps.add(b.nodes[v].get("label") or v)
        for u, _, data in b.graph.in_edges(nid, data=True):
            if data.get("relation") in {"imports", "imports_from", "calls", "uses", "references"}:
                users.add(b.nodes[u].get("label") or u)

    purpose = (
        f"{seed_n.get('label')} ({seed_n.get('kind')}) in "
        f"{seed_n.get('source_file') or 'unknown path'}"
    )
    return {
        "module": seed_n.get("label"),
        "seed": _public_node(seed_n),
        "purpose": purpose,
        "responsibilities": [
            f"Primary artifact: {seed_n.get('label')}",
            f"File type: {seed_n.get('file_type')}",
            f"Community: {comm}",
        ],
        "important_files": sorted(files)[:25],
        "important_classes": sorted(set(classes))[:20],
        "important_functions": sorted(set(functions))[:30],
        "dependencies": sorted(deps)[:30],
        "downstream_users": sorted(users)[:30],
    }


def explain_flow(start: str, end: str, bundle: Optional[GraphBundle] = None) -> Dict[str, Any]:
    path = shortest_path(start, end, bundle=bundle)
    if path.get("error") and not path.get("path"):
        return path
    labels = path.get("path_labels") or [p.get("label") for p in path.get("path") or []]
    explanation = (
        " → ".join(str(x) for x in labels)
        if labels
        else "No connecting path found in the architecture graph."
    )
    narrative = (
        f"Flow from {labels[0]} to {labels[-1]} crosses {len(labels) - 1} hop(s): {explanation}. "
        "Edges come from Graphify AST/semantic extraction (imports, calls, contains, references)."
        if labels
        else explanation
    )
    return {
        **path,
        "graph_path": explanation,
        "explanation": narrative,
    }


def architecture(question: str, *, limit: int = 12, bundle: Optional[GraphBundle] = None) -> Dict[str, Any]:
    """NL architecture Q&A backed by graph search + neighborhood expansion."""
    b = bundle or get_bundle()
    q = (question or "").strip()
    stop = {
        "how", "does", "do", "the", "a", "an", "what", "is", "are", "explain",
        "work", "works", "about", "with", "from", "into", "for", "and", "or",
        "this", "that", "please", "me", "in", "of", "to", "on", "engine",
        "system", "code", "our", "my",
    }
    seeds = search_nodes(q, limit=8, bundle=b)
    cleaned = re.sub(
        r"\b(" + "|".join(stop) + r")\b",
        " ",
        q,
        flags=re.I,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if cleaned and cleaned.lower() != q.lower():
        seeds = _merge_hits(seeds, search_nodes(cleaned, limit=8, bundle=b))
    # Token queries for multi-word topics (e.g. "adaptive chunking")
    tokens = [t for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", cleaned or q) if t.lower() not in stop]
    for tok in tokens[:4]:
        seeds = _merge_hits(seeds, search_nodes(tok, limit=5, bundle=b))

    supporting: Dict[str, Dict[str, Any]] = {}
    for s in seeds:
        supporting[s["id"]] = {**s, "role": "seed"}
        nb = neighbors(s["id"], limit=15, bundle=b)
        for n in nb.get("neighbors") or []:
            oid = n["id"]
            if oid not in supporting:
                supporting[oid] = {**n, "role": "neighbor", "score": (s.get("score") or 0) * 0.7}

    def _rank_key(x: Dict[str, Any]) -> Tuple[float, int]:
        score = float(x.get("score") or 0)
        sf = (x.get("source_file") or "").replace("\\", "/")
        if sf.startswith(("backend/src/", "frontend/src/", "frontend/app/")):
            score += 12.0
        kind = x.get("kind") or ""
        if kind in {"class", "function", "module", "file", "code"}:
            score += 6.0
        return (-score, -b.degree.get(x["id"], 0))

    ranked = sorted(supporting.values(), key=_rank_key)[:limit]

    files = []
    seen_f = set()
    for n in ranked:
        sf = n.get("source_file")
        if sf and sf not in seen_f:
            seen_f.add(sf)
            files.append(sf)

    top_labels = [n.get("label") for n in ranked[:6] if n.get("label")]
    explanation = (
        f"For “{q}”, the architecture graph highlights: "
        + ", ".join(top_labels)
        + ". "
        + (
            f"Key files: {', '.join(files[:8])}."
            if files
            else "No primary source files were attached to the top nodes."
        )
    )
    return {
        "question": q,
        "explanation": explanation,
        "nodes": ranked,
        "supporting_files": files[:20],
        "seed_count": len(seeds),
    }
