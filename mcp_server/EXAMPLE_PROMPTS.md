# Example Cursor prompts (Architecture Intelligence MCP)

Use after the `architecture-intelligence` MCP server is enabled.

## Discovery

- Using architecture tools, search_nodes for "carbon router" and summarize what you find.
- locate "JWT authentication" and list the supporting files.
- architecture: How does adaptive chunking work?
- architecture: Explain carbon accounting.
- architecture: How are jobs scheduled?

## Structure & flow

- explain_flow from Document Upload concepts to Final Report / response agent.
- shortest_path between ChunkRouter and SummaryAgent.
- module_summary for backend/src/core/orchestrator.
- dependencies of the orchestrator; then reverse_dependencies.

## Impact & health

- impact of changing CarbonRouter — which files are affected?
- hotspots — highest degree nodes and largest communities.
- community for the largest community id from hotspots.
- architecture_report including circular_dependencies and most_reused.
- architecture_map focused on the chunk router (Mermaid).

## Rule of thumb

If the graph can answer it, call MCP tools first — do not start with a broad codebase grep.
