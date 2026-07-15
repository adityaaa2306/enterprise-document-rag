"""Architecture Intelligence MCP server (stdio).

Loads graphify-out/graph.json once, then exposes graph query tools to Cursor.

Run (from repo root):
  backend\\.venv\\Scripts\\python.exe -m mcp_server.main
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Allow `python mcp_server/main.py` as well as `python -m mcp_server.main`
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from mcp.server.fastmcp import FastMCP

from mcp_server.graph_loader import get_bundle
from mcp_server.tool_registry import register_tools

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("architecture_mcp")

mcp = FastMCP(
    "architecture-intelligence",
    instructions=(
        "AI Architecture Explorer for this repository. "
        "Prefer these tools over raw codebase search when the question is about "
        "structure, dependencies, flows, modules, or impact analysis. "
        "Start with architecture(question) or search_nodes / locate for discovery."
    ),
)


def bootstrap() -> None:
    register_tools(mcp)
    # Eager-load graph so first tool call is fast
    b = get_bundle()
    log.info(
        "Architecture MCP ready — %s nodes, %s edges (%.0f ms)",
        b.node_count,
        b.edge_count,
        b.load_ms,
    )


bootstrap()


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
