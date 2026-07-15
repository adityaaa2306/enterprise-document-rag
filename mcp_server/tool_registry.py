"""Register Architecture Intelligence tools on a FastMCP server."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from mcp.server.fastmcp import FastMCP

from mcp_server import graph_analysis, graph_queries
from mcp_server.graph_loader import get_bundle


def register_tools(mcp: FastMCP) -> FastMCP:
    """Attach all graph tools to the given FastMCP instance."""

    @mcp.tool()
    def search_nodes(
        query: str,
        limit: int = 20,
        kinds: Optional[str] = None,
        file_contains: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fuzzy-search architecture graph nodes by name/label.

        kinds: optional comma-separated filter —
        file, class, function, module, document, readme, image, paper.
        """
        kind_list: Optional[List[str]] = None
        if kinds:
            kind_list = [k.strip() for k in kinds.split(",") if k.strip()]
        hits = graph_queries.search_nodes(
            query, limit=limit, kinds=kind_list, file_contains=file_contains
        )
        return {"query": query, "count": len(hits), "nodes": hits}

    @mcp.tool()
    def neighbors(
        node: str,
        relation: Optional[str] = None,
        direction: str = "both",
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Return nodes directly connected to `node` (label or id)."""
        return graph_queries.neighbors(
            node, relation=relation, direction=direction, limit=limit
        )

    @mcp.tool()
    def shortest_path(node_a: str, node_b: str) -> Dict[str, Any]:
        """Shortest undirected path between two architecture nodes."""
        return graph_queries.shortest_path(node_a, node_b)

    @mcp.tool()
    def module_summary(module: str) -> Dict[str, Any]:
        """Concise architecture summary of a module/package/file cluster."""
        return graph_queries.module_summary(module)

    @mcp.tool()
    def explain_flow(start: str, end: str) -> Dict[str, Any]:
        """Explain a flow between two components with path + narrative."""
        return graph_queries.explain_flow(start, end)

    @mcp.tool()
    def dependencies(node: str) -> Dict[str, Any]:
        """Outbound deps: imports, calls, inherits, references, documents."""
        return graph_queries.dependencies(node)

    @mcp.tool()
    def reverse_dependencies(node: str, limit: int = 80) -> Dict[str, Any]:
        """Who depends on this node (inbound edges)."""
        return graph_queries.reverse_dependencies(node, limit=limit)

    @mcp.tool()
    def architecture(question: str, limit: int = 12) -> Dict[str, Any]:
        """Natural-language architecture Q&A backed by the Graphify graph.

        Prefer this over repository search when asking how a subsystem works.
        """
        return graph_queries.architecture(question, limit=limit)

    @mcp.tool()
    def hotspots(top: int = 25) -> Dict[str, Any]:
        """Highest-degree / betweenness nodes and largest communities."""
        return graph_analysis.hotspots(top=top)

    @mcp.tool()
    def community(id: int, limit: int = 80) -> Dict[str, Any]:
        """Summarize a community by numeric id from Graphify / hotspots()."""
        return graph_analysis.community(id, limit=limit)

    @mcp.tool()
    def impact(node: str, depth: int = 2, limit: int = 60) -> Dict[str, Any]:
        """If this node changes, which files/nodes are likely affected?"""
        return graph_queries.impact(node, depth=depth, limit=limit)

    @mcp.tool()
    def locate(feature: str, limit: int = 25) -> Dict[str, Any]:
        """Locate files and nodes implementing a feature or concept."""
        return graph_queries.locate(feature, limit=limit)

    @mcp.tool()
    def architecture_map(
        focus: Optional[str] = None,
        depth: int = 2,
        limit: int = 40,
    ) -> Dict[str, Any]:
        """Mermaid flowchart for a focus neighborhood or top hotspots."""
        return graph_analysis.architecture_map(focus=focus, depth=depth, limit=limit)

    @mcp.tool()
    def architecture_report(
        include: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Health report: dead code, cycles, reuse, coupling, communities.

        include: comma-separated subset of
        dead_code, circular_dependencies, largest_communities,
        most_reused, hidden_coupling, layer_violations.
        """
        parts: Optional[List[str]] = None
        if include:
            parts = [p.strip() for p in include.split(",") if p.strip()]
        return graph_analysis.architecture_report(include=parts)

    @mcp.tool()
    def graph_stats() -> Dict[str, Any]:
        """Loaded graph size and path (sanity / diagnostics)."""
        b = get_bundle()
        return {
            "path": str(b.path),
            "nodes": b.node_count,
            "edges": b.edge_count,
            "communities": len(b.by_community),
            "load_ms": round(b.load_ms, 1),
        }

    return mcp
