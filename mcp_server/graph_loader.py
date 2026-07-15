"""Load graphify-out/graph.json into NetworkX once and build lookup indexes."""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import networkx as nx

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRAPH_PATH = REPO_ROOT / "graphify-out" / "graph.json"

_FILE_EXT_RE = re.compile(r"\.(py|ts|tsx|js|jsx|md|pdf|png|jpg|jpeg|svg|yml|yaml|toml|json|sh|ps1)$", re.I)


@dataclass
class GraphBundle:
    """In-memory graph + indexes. Constructed once at process start."""

    path: Path
    graph: nx.MultiDiGraph
    nodes: Dict[str, Dict[str, Any]]
    # indexes
    by_label: Dict[str, List[str]] = field(default_factory=dict)
    by_norm_label: Dict[str, List[str]] = field(default_factory=dict)
    by_file: Dict[str, List[str]] = field(default_factory=dict)
    by_type: Dict[str, List[str]] = field(default_factory=dict)
    by_kind: Dict[str, List[str]] = field(default_factory=dict)
    by_community: Dict[int, List[str]] = field(default_factory=dict)
    # precomputed metrics (lazy-filled by analysis)
    degree: Dict[str, int] = field(default_factory=dict)
    betweenness: Dict[str, float] = field(default_factory=dict)
    load_ms: float = 0.0
    node_count: int = 0
    edge_count: int = 0

    def node(self, node_id: str) -> Optional[Dict[str, Any]]:
        return self.nodes.get(node_id)


def _norm(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9_./\\+\-]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def classify_kind(node: Dict[str, Any]) -> str:
    """Map graphify node → coarse kind for filtering."""
    ft = (node.get("file_type") or "").lower()
    label = node.get("label") or ""
    src = (node.get("source_file") or "").replace("\\", "/")
    low_label = label.lower()
    low_src = src.lower()

    if ft == "image" or low_src.endswith((".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif")):
        return "image"
    if ft == "document" or low_src.endswith((".pdf", ".docx")):
        if "paper" in low_label or "paper" in low_src or low_src.endswith(".pdf"):
            return "paper"
        return "document"
    if "readme" in low_label or "readme" in low_src:
        return "readme"
    if ft in {"concept", "rationale"}:
        return ft

    # code-ish
    if _FILE_EXT_RE.search(label) or (src and label == Path(src).name):
        return "file"
    if label.endswith("()") or (label and label[0].islower() and "(" not in label and "." not in label):
        # functions often end with () in graphify AST; bare snake_case may be func/id
        if label.endswith("()"):
            return "function"
    if label.endswith("()"):
        return "function"
    if label[:1].isupper() and "." not in label and " " not in label and not label.endswith("()"):
        return "class"
    # path-like modules
    if "/" in src:
        parts = src.split("/")
        if len(parts) >= 2 and not label.endswith("()"):
            if label.lower() in {parts[-2].lower(), parts[-1].lower().rsplit(".", 1)[0]}:
                return "module"
    if ft == "code":
        if label.endswith("()"):
            return "function"
        if label[:1].isupper() and " " not in label:
            return "class"
        return "code"
    return ft or "unknown"


def load_graph(path: Optional[Path] = None) -> GraphBundle:
    t0 = time.perf_counter()
    graph_path = Path(path) if path else DEFAULT_GRAPH_PATH
    if not graph_path.exists():
        raise FileNotFoundError(f"Graph not found: {graph_path}")

    raw = json.loads(graph_path.read_text(encoding="utf-8"))
    nodes_list: List[Dict[str, Any]] = list(raw.get("nodes") or [])
    links: List[Dict[str, Any]] = list(raw.get("links") or raw.get("edges") or [])

    g = nx.MultiDiGraph()
    nodes: Dict[str, Dict[str, Any]] = {}

    for n in nodes_list:
        nid = str(n.get("id") or "")
        if not nid:
            continue
        kind = classify_kind(n)
        meta = {
            **n,
            "id": nid,
            "kind": kind,
            "norm_label": n.get("norm_label") or _norm(n.get("label") or nid),
            "source_file": (n.get("source_file") or "").replace("\\", "/"),
        }
        nodes[nid] = meta
        g.add_node(nid, **{k: v for k, v in meta.items() if k != "id"})

    for e in links:
        src = str(e.get("source") or "")
        tgt = str(e.get("target") or "")
        if not src or not tgt:
            continue
        if src not in nodes or tgt not in nodes:
            continue
        g.add_edge(
            src,
            tgt,
            relation=e.get("relation") or "related",
            confidence=e.get("confidence"),
            weight=float(e.get("weight") or 1.0),
            source_file=(e.get("source_file") or "").replace("\\", "/"),
            confidence_score=e.get("confidence_score"),
            _origin=e.get("_origin"),
        )

    bundle = GraphBundle(
        path=graph_path,
        graph=g,
        nodes=nodes,
        load_ms=0.0,
        node_count=g.number_of_nodes(),
        edge_count=g.number_of_edges(),
    )
    _build_indexes(bundle)

    # degree always; betweenness deferred (expensive) — computed on first hotspots()
    und = g.to_undirected()
    bundle.degree = {n: int(d) for n, d in und.degree()}

    bundle.load_ms = (time.perf_counter() - t0) * 1000.0
    log.info(
        "Loaded graph %s: %s nodes, %s edges in %.1f ms",
        graph_path,
        bundle.node_count,
        bundle.edge_count,
        bundle.load_ms,
    )
    return bundle


def _build_indexes(bundle: GraphBundle) -> None:
    by_label: Dict[str, List[str]] = {}
    by_norm: Dict[str, List[str]] = {}
    by_file: Dict[str, List[str]] = {}
    by_type: Dict[str, List[str]] = {}
    by_kind: Dict[str, List[str]] = {}
    by_community: Dict[int, List[str]] = {}

    for nid, n in bundle.nodes.items():
        label = n.get("label") or ""
        by_label.setdefault(label.lower(), []).append(nid)
        by_norm.setdefault(_norm(label), []).append(nid)
        by_norm.setdefault(_norm(nid.replace("_", " ")), []).append(nid)

        sf = n.get("source_file") or ""
        if sf:
            by_file.setdefault(sf.lower(), []).append(nid)
            by_file.setdefault(Path(sf).name.lower(), []).append(nid)

        ft = (n.get("file_type") or "unknown").lower()
        by_type.setdefault(ft, []).append(nid)

        kind = (n.get("kind") or "unknown").lower()
        by_kind.setdefault(kind, []).append(nid)

        comm = n.get("community")
        if comm is not None:
            try:
                by_community.setdefault(int(comm), []).append(nid)
            except (TypeError, ValueError):
                pass

    bundle.by_label = by_label
    bundle.by_norm_label = by_norm
    bundle.by_file = by_file
    bundle.by_type = by_type
    bundle.by_kind = by_kind
    bundle.by_community = by_community


def ensure_betweenness(bundle: GraphBundle, *, k: int = 200) -> None:
    """Approx betweenness (sampled) — cached after first call."""
    if bundle.betweenness:
        return
    t0 = time.perf_counter()
    und = bundle.graph.to_undirected()
    # Sampled betweenness for speed on ~4k nodes
    sample = min(k, max(10, und.number_of_nodes() // 10))
    try:
        bundle.betweenness = nx.betweenness_centrality(und, k=sample, seed=42)
    except Exception:
        bundle.betweenness = {n: 0.0 for n in und.nodes()}
    log.info("Betweenness (k=%s) computed in %.1f ms", sample, (time.perf_counter() - t0) * 1000.0)


# Singleton used by MCP tools
_BUNDLE: Optional[GraphBundle] = None


def get_bundle(path: Optional[Path] = None, *, reload: bool = False) -> GraphBundle:
    global _BUNDLE
    if _BUNDLE is None or reload:
        _BUNDLE = load_graph(path)
    return _BUNDLE
