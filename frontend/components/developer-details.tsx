"use client"

import type { ReactNode } from "react"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { ChevronDown } from "lucide-react"
import { cn } from "@/lib/utils"
import type { RetrievedChunkMeta } from "@/components/answer-sources"

export type DeveloperDetailsProps = {
  reasoningPath?: string[] | null
  retrievedChunks?: RetrievedChunkMeta[] | null
  modelUsed?: string | null
  skill?: string | null
  confidence?: number | null
  latencyMs?: number | null
  entitiesUsed?: string[] | null
  missingContext?: string[] | null
  knowledgeSources?: string[] | null
  documentsRetrieved?: number | null
  className?: string
}

function DebugRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-1">
      <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <div className="text-xs text-foreground/90 leading-relaxed">{children}</div>
    </div>
  )
}

export function DeveloperDetails({
  reasoningPath,
  retrievedChunks,
  modelUsed,
  skill,
  confidence,
  latencyMs,
  entitiesUsed,
  missingContext,
  knowledgeSources,
  documentsRetrieved,
  className,
}: DeveloperDetailsProps) {
  const hasContent =
    (reasoningPath && reasoningPath.length > 0) ||
    (retrievedChunks && retrievedChunks.length > 0) ||
    modelUsed ||
    skill ||
    confidence != null ||
    latencyMs != null ||
    (entitiesUsed && entitiesUsed.length > 0) ||
    (missingContext && missingContext.length > 0) ||
    (knowledgeSources && knowledgeSources.length > 0) ||
    documentsRetrieved != null

  if (!hasContent) return null

  return (
    <Collapsible className={cn("mt-3", className)}>
      <CollapsibleTrigger className="group flex w-full items-center justify-between rounded-lg border border-border/40 bg-muted/30 px-3 py-2 text-left text-xs font-medium text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground">
        <span>Developer Details</span>
        <ChevronDown className="h-3.5 w-3.5 transition-transform group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-2 space-y-3 rounded-lg border border-border/40 bg-background/40 p-3">
        {reasoningPath && reasoningPath.length > 0 ? (
          <DebugRow label="Reasoning Path">
            <ol className="list-decimal space-y-0.5 pl-4 font-mono">
              {reasoningPath.map((step, i) => (
                <li key={`${step}-${i}`}>{step}</li>
              ))}
            </ol>
          </DebugRow>
        ) : null}

        {skill ? (
          <DebugRow label="Skill">
            <code className="rounded bg-muted px-1.5 py-0.5">{skill}</code>
          </DebugRow>
        ) : null}

        {modelUsed ? (
          <DebugRow label="Model ID">
            <code className="break-all rounded bg-muted px-1.5 py-0.5">
              {modelUsed}
            </code>
          </DebugRow>
        ) : null}

        {confidence != null ? (
          <DebugRow label="Confidence">{(confidence * 100).toFixed(1)}%</DebugRow>
        ) : null}

        {latencyMs != null ? (
          <DebugRow label="Latency">{latencyMs} ms</DebugRow>
        ) : null}

        {documentsRetrieved != null ? (
          <DebugRow label="Retrieved Context Count">{documentsRetrieved}</DebugRow>
        ) : null}

        {retrievedChunks && retrievedChunks.length > 0 ? (
          <DebugRow label="Retrieved Chunks">
            <ul className="space-y-1.5">
              {retrievedChunks.map((chunk, i) => (
                <li
                  key={`${chunk.id || i}-${i}`}
                  className="rounded border border-border/30 bg-muted/20 px-2 py-1.5 font-mono"
                >
                  <div>id: {chunk.id || "—"}</div>
                  <div>
                    score: {chunk.score != null ? chunk.score.toFixed(3) : "—"}
                    {chunk.citation != null ? ` · citation: [${chunk.citation}]` : ""}
                  </div>
                  {chunk.parent_section ? (
                    <div className="truncate">section: {chunk.parent_section}</div>
                  ) : null}
                </li>
              ))}
            </ul>
          </DebugRow>
        ) : null}

        {entitiesUsed && entitiesUsed.length > 0 ? (
          <DebugRow label="Entities Used">{entitiesUsed.join(", ")}</DebugRow>
        ) : null}

        {missingContext && missingContext.length > 0 ? (
          <DebugRow label="Missing Context">
            <span className="text-amber-300/90">{missingContext.join("; ")}</span>
          </DebugRow>
        ) : null}

        {knowledgeSources && knowledgeSources.length > 0 ? (
          <DebugRow label="Knowledge Sources">
            <ul className="list-disc space-y-0.5 pl-4 font-mono">
              {knowledgeSources.slice(0, 12).map((src, i) => (
                <li key={`${src}-${i}`} className="break-all">
                  {src}
                </li>
              ))}
            </ul>
          </DebugRow>
        ) : null}
      </CollapsibleContent>
    </Collapsible>
  )
}
