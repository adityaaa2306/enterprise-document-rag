"use client"

import { Card } from "@/components/ui/card"
import { cn } from "@/lib/utils"

export type StructureNode = {
  id?: string
  heading?: string
  level?: number
  tokens?: number
  children?: StructureNode[]
  blocks?: Array<{ kind?: string; preview?: string }>
}

export type StructureDiagnostics = {
  raw_layout_blocks?: number
  validated_headings?: number
  rejected_headings?: number
  semantic_sections?: number
  merged_sections?: number
  packed_chunks?: number
  average_chunk_tokens?: number
  median_chunk_tokens?: number
  min_chunk_tokens?: number
  max_chunk_tokens?: number
}

function TreeNode({ node, depth = 0 }: { node: StructureNode; depth?: number }) {
  const kids = node.children || []
  const blocks = node.blocks || []
  return (
    <li className="font-mono text-[11px] leading-relaxed">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="text-foreground/90">
          {"│  ".repeat(Math.max(0, depth - 1))}
          {depth > 0 ? "├── " : ""}
          {node.heading || "Section"}
        </span>
        {node.tokens != null ? (
          <span className="text-muted-foreground">({node.tokens} tok)</span>
        ) : null}
      </div>
      {blocks.length > 0 ? (
        <ul className="ml-4 list-none text-muted-foreground">
          {blocks.slice(0, 8).map((b, i) => (
            <li key={`${node.id}-b-${i}`}>
              └── {b.kind || "block"}
              {b.preview ? `: ${b.preview.slice(0, 72)}` : ""}
            </li>
          ))}
        </ul>
      ) : null}
      {kids.length > 0 ? (
        <ul className="ml-2 list-none">
          {kids.map((c, i) => (
            <TreeNode key={c.id || `${node.id}-${i}`} node={c} depth={depth + 1} />
          ))}
        </ul>
      ) : null}
    </li>
  )
}

export function DocumentStructureViewer({
  tree,
  diagnostics,
  className,
}: {
  tree?: StructureNode[] | null
  diagnostics?: StructureDiagnostics | null
  className?: string
}) {
  const nodes = tree || []
  const d = diagnostics || {}
  if (!nodes.length && !d.packed_chunks && !d.validated_headings) return null

  return (
    <Card className={cn("p-6 bg-card/50 border-border/50 space-y-4", className)}>
      <div>
        <h3 className="text-lg font-semibold">Document Structure</h3>
        <p className="text-xs text-muted-foreground mt-1">
          Validated headings → semantic sections (developer view)
        </p>
      </div>

      {(d.raw_layout_blocks != null || d.packed_chunks != null) && (
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="rounded-md bg-muted/40 px-2 py-1.5">
            Layout blocks: <strong>{d.raw_layout_blocks ?? "—"}</strong>
          </div>
          <div className="rounded-md bg-muted/40 px-2 py-1.5">
            Validated headings: <strong>{d.validated_headings ?? "—"}</strong>
          </div>
          <div className="rounded-md bg-muted/40 px-2 py-1.5">
            Rejected: <strong>{d.rejected_headings ?? "—"}</strong>
          </div>
          <div className="rounded-md bg-muted/40 px-2 py-1.5">
            Packed chunks: <strong>{d.packed_chunks ?? "—"}</strong>
          </div>
          <div className="rounded-md bg-muted/40 px-2 py-1.5 col-span-2">
            Tokens avg/med/min/max:{" "}
            <strong>
              {d.average_chunk_tokens ?? "—"} / {d.median_chunk_tokens ?? "—"} /{" "}
              {d.min_chunk_tokens ?? "—"} / {d.max_chunk_tokens ?? "—"}
            </strong>
          </div>
        </div>
      )}

      {nodes.length > 0 ? (
        <div className="max-h-96 overflow-auto rounded-md border border-border/40 bg-background/50 p-3">
          <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            Document
          </p>
          <ul className="list-none space-y-1">
            {nodes.map((n, i) => (
              <TreeNode key={n.id || `root-${i}`} node={n} depth={0} />
            ))}
          </ul>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">No structure tree for this job.</p>
      )}
    </Card>
  )
}
