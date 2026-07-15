# Architecture Intelligence MCP

Graph-backed architecture explorer for this repo. Cursor talks to it over MCP; it is **not** another RAG pipeline.

## What it does

Loads `graphify-out/graph.json` **once** into NetworkX, builds indexes, and exposes tools like `architecture`, `search_nodes`, `explain_flow`, `impact`, and `hotspots`.

Prefer these tools over manual repo search when the question is about structure, dependencies, or flows.

## Layout

```
mcp_server/
  graph_loader.py      # load + indexes (singleton)
  graph_cache.py       # LRU helpers
  graph_queries.py     # search, path, deps, locate, architecture Q&A
  graph_analysis.py    # hotspots, communities, Mermaid, health reports
  tool_registry.py     # FastMCP tool wiring
  main.py              # stdio entrypoint
  requirements.txt
tests/
  test_mcp_graph.py
```

## Setup

```powershell
cd D:\green-agentic-rag-main
.\backend\.venv\Scripts\pip.exe install -r mcp_server\requirements.txt
```

Ensure `graphify-out/graph.json` exists (from Graphify).

## Cursor config

Project file: `.cursor/mcp.json` (stdio → `backend/.venv` + `python -m mcp_server.main`).

Reload the Cursor window after changing MCP config. Confirm tools under **architecture-intelligence**.

Manual smoke (stdio handshake is MCP-owned; query engine alone):

```powershell
$env:PYTHONPATH = "D:\green-agentic-rag-main"
.\backend\.venv\Scripts\python.exe -c "from mcp_server.graph_loader import get_bundle; from mcp_server.graph_queries import search_nodes, architecture; b=get_bundle(); print(b.node_count, b.edge_count); print(search_nodes('carbon', limit=5)); print(architecture('How does carbon accounting work?')['explanation'][:400])"
```

## Tools

| Tool | Purpose |
|------|---------|
| `search_nodes` | Fuzzy node search (+ optional kind/file filters) |
| `neighbors` | Direct connections |
| `shortest_path` | Path between two nodes |
| `module_summary` | Module purpose / files / deps / users |
| `explain_flow` | Path + natural-language flow |
| `dependencies` | imports / calls / inherits / references / documents |
| `reverse_dependencies` | Who depends on this node |
| `architecture` | NL architecture Q&A |
| `hotspots` | Degree, betweenness, large communities |
| `community` | Community summary by id |
| `impact` | Blast radius if a node changes |
| `locate` | Feature → files |
| `architecture_map` | Mermaid neighborhood |
| `architecture_report` | Cycles, dead-ish nodes, coupling, reuse |
| `graph_stats` | Load diagnostics |

## Example prompts (in Cursor)

- “Using architecture tools, explain how adaptive chunking works.”
- “Locate JWT authentication in the graph and list supporting files.”
- “What is the impact of changing CarbonRouter?”
- “Show the flow from document upload to final report.”
- “Hotspots and largest communities in this architecture.”
- “Module summary for backend/src/core/orchestrator.”
- “Draw an architecture_map focused on the chunk router.”

## Tests

```powershell
$env:PYTHONPATH = "D:\green-agentic-rag-main"
.\backend\.venv\Scripts\python.exe -m pytest mcp_server\tests -q
```

## Performance notes

- Graph loaded once at process start (`get_bundle()` singleton).
- Degree always cached; betweenness sampled on first `hotspots()` call.
- Target: typical tool calls well under 100 ms after load (betweenness first call is slower).

## Regenerating the graph

Re-run Graphify (see `scripts/run-graphify.ps1`), then restart the MCP server so it reloads `graph.json`.
