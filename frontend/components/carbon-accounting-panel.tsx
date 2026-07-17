"use client"

import { useState } from "react"
import { ChevronDown, Info, Leaf } from "lucide-react"
import { cn } from "@/lib/utils"
import { fmtG, fmtIntensity } from "@/lib/job-results-metrics"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

export type RagCarbonSnapshot = {
  estimated_gco2e?: number | null
  estimated_energy_kwh?: number | null
  estimated_energy_wh?: number | null
  grid_intensity_gco2_kwh?: number | null
  stages_gco2e?: {
    query_embedding_gco2e?: number
    retrieval_gco2e?: number
    prompt_inference_gco2e?: number
    completion_inference_gco2e?: number
    llm_inference_gco2e?: number
  } | null
}

export type CarbonTimelineEntry = {
  id: string
  label: string
  gco2e: number
  kind: "document" | "query"
}

const DOC_METHOD =
  "Includes document parsing, chunking, embeddings, routed summarization, and compilation. This is a one-time ingestion cost for the document job — not chat."

const RAG_METHOD =
  "Includes query embedding (if used), retrieval, prompt processing, and answer generation for this query. Independent of Document Processing CO₂e."

const LIFETIME_METHOD =
  "Derived summary only: Document Processing CO₂e + session Interactive RAG totals. Not a separate measurement — keeps both workloads visible while showing cumulative cost."

function fmtQueryG(n: number | undefined | null): string {
  if (n == null || !Number.isFinite(Number(n))) return "—"
  const v = Number(n)
  if (v > 0 && v < 0.01) return `${v.toFixed(4)} g`
  if (v < 1) return `${v.toFixed(3)} g`
  return fmtG(v)
}

function InfoTip({ text }: { text: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          className="inline-flex h-4 w-4 items-center justify-center rounded-full text-muted-foreground hover:text-foreground"
          aria-label="About this metric"
        >
          <Info className="h-3 w-3" />
        </button>
      </TooltipTrigger>
      <TooltipContent className="max-w-[260px] text-xs leading-relaxed">
        {text}
      </TooltipContent>
    </Tooltip>
  )
}

type Props = {
  documentGco2e: number
  /** Latest (or focused) per-query estimate */
  lastQueryGco2e?: number | null
  sessionQueries: number
  sessionGco2e: number
  /** Optional grid intensity from last RAG estimate */
  gridIntensity?: number | null
  timeline?: CarbonTimelineEntry[]
  className?: string
  compact?: boolean
}

/**
 * Clarifies how Document Processing and Interactive RAG relate,
 * with methodology tips and a derived lifetime total.
 */
export function CarbonAccountingPanel({
  documentGco2e,
  lastQueryGco2e,
  sessionQueries,
  sessionGco2e,
  gridIntensity,
  timeline,
  className,
  compact = false,
}: Props) {
  const [methodOpen, setMethodOpen] = useState(false)
  const docG = Number.isFinite(documentGco2e) ? Math.max(0, documentGco2e) : 0
  const sessionG = Number.isFinite(sessionGco2e) ? Math.max(0, sessionGco2e) : 0
  const lifetimeG = docG + sessionG
  const queryG =
    lastQueryGco2e != null && Number.isFinite(Number(lastQueryGco2e))
      ? Number(lastQueryGco2e)
      : null

  return (
    <div
      className={cn(
        "rounded-xl border border-border/50 bg-card/50",
        compact ? "p-3" : "p-3.5",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Leaf className="h-3.5 w-3.5 text-emerald-400" />
          <p className="text-xs font-semibold uppercase tracking-wide text-foreground">
            Carbon Accounting
          </p>
        </div>
        <InfoTip text="Two independent workloads share the same energy model (J/token × PUE × grid intensity). They are reported separately so ingestion and chat are never confused." />
      </div>

      {/* Document Processing */}
      <div className="mt-3 border-t border-border/40 pt-3">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <p className="text-sm font-medium text-foreground">Document Processing</p>
              <InfoTip text={DOC_METHOD} />
            </div>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              One-time ingestion cost
            </p>
          </div>
          <p className="shrink-0 text-sm font-semibold tabular-nums text-foreground">
            {fmtG(docG)}
          </p>
        </div>
      </div>

      {/* Interactive RAG */}
      <div className="mt-3 border-t border-border/40 pt-3">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <p className="text-sm font-medium text-foreground">Interactive RAG</p>
              <InfoTip text={RAG_METHOD} />
            </div>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              {queryG != null
                ? `${fmtQueryG(queryG)} CO₂e / query`
                : "Per-query chat emissions"}
            </p>
          </div>
          <div className="shrink-0 text-right">
            <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
              Session total
            </p>
            <p className="text-sm font-semibold tabular-nums text-foreground">
              {sessionQueries > 0 ? fmtQueryG(sessionG) : "—"}
            </p>
            <p className="text-[11px] text-muted-foreground">
              {sessionQueries > 0
                ? `${sessionQueries} question${sessionQueries === 1 ? "" : "s"}`
                : "No queries yet"}
            </p>
          </div>
        </div>
        {gridIntensity != null && Number.isFinite(Number(gridIntensity)) ? (
          <p className="mt-1.5 text-[10px] text-muted-foreground">
            Grid intensity used · {fmtIntensity(gridIntensity)}
          </p>
        ) : null}
      </div>

      {/* Lifetime (derived) */}
      <div className="mt-3 rounded-lg border border-dashed border-border/50 bg-muted/15 px-2.5 py-2">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <p className="text-[11px] font-medium text-muted-foreground">
              Lifetime Carbon
            </p>
            <InfoTip text={LIFETIME_METHOD} />
          </div>
          <p className="text-xs font-semibold tabular-nums text-foreground">
            {fmtQueryG(lifetimeG)} CO₂e
          </p>
        </div>
        <p className="mt-1 text-[10px] leading-relaxed text-muted-foreground tabular-nums">
          {fmtG(docG)} <span className="opacity-60">+</span>{" "}
          {sessionQueries > 0 ? fmtQueryG(sessionG) : "0 g"}{" "}
          <span className="opacity-60">=</span> {fmtQueryG(lifetimeG)}
          <span className="ml-1 opacity-70">(derived · not primary)</span>
        </p>
      </div>

      {/* Methodology expandable */}
      <Collapsible open={methodOpen} onOpenChange={setMethodOpen} className="mt-2">
        <CollapsibleTrigger className="group flex w-full items-center justify-between rounded-md px-0.5 py-1 text-[11px] text-muted-foreground hover:text-foreground">
          <span>What each metric includes</span>
          <ChevronDown className="h-3.5 w-3.5 transition-transform group-data-[state=open]:rotate-180" />
        </CollapsibleTrigger>
        <CollapsibleContent className="space-y-2 px-0.5 pb-0.5 text-[11px] leading-relaxed text-muted-foreground">
          <p>
            <span className="font-medium text-foreground/90">Document Processing — </span>
            {DOC_METHOD}
          </p>
          <p>
            <span className="font-medium text-foreground/90">Interactive RAG — </span>
            {RAG_METHOD}
          </p>
          <p>
            <span className="font-medium text-foreground/90">Lifetime Carbon — </span>
            {LIFETIME_METHOD}
          </p>
        </CollapsibleContent>
      </Collapsible>

      {/* Lightweight carbon timeline */}
      {timeline && timeline.length > 0 ? (
        <Collapsible className="mt-2 border-t border-border/40 pt-2">
          <CollapsibleTrigger className="group flex w-full items-center justify-between rounded-md px-0.5 py-1 text-[11px] text-muted-foreground hover:text-foreground">
            <span>Carbon Timeline</span>
            <ChevronDown className="h-3.5 w-3.5 transition-transform group-data-[state=open]:rotate-180" />
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-1.5 space-y-0">
            <ul className="relative space-y-0 pl-3">
              <span
                className="absolute left-[5px] top-1.5 bottom-1.5 w-px bg-border/60"
                aria-hidden
              />
              {timeline.map((entry) => (
                <li key={entry.id} className="relative flex items-start gap-2.5 py-1.5">
                  <span
                    className={cn(
                      "relative z-[1] mt-1.5 h-2 w-2 shrink-0 rounded-full border",
                      entry.kind === "document"
                        ? "border-emerald-400/80 bg-emerald-500/40"
                        : "border-border bg-muted",
                    )}
                  />
                  <div className="min-w-0 flex-1 flex items-baseline justify-between gap-2">
                    <span className="truncate text-[11px] text-foreground/85">
                      {entry.label}
                    </span>
                    <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
                      {entry.kind === "document"
                        ? fmtG(entry.gco2e)
                        : fmtQueryG(entry.gco2e)}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          </CollapsibleContent>
        </Collapsible>
      ) : null}
    </div>
  )
}

/** Compact per-answer card (keeps stage breakdown). */
export function InteractiveRagQueryCarbon({
  carbon,
}: {
  carbon: RagCarbonSnapshot
}) {
  const stages = carbon.stages_gco2e || {}
  const llmG =
    stages.llm_inference_gco2e ??
    Number(stages.prompt_inference_gco2e || 0) +
      Number(stages.completion_inference_gco2e || 0)

  return (
    <div className="mt-2 rounded-xl border border-emerald-500/25 bg-emerald-500/5 p-3">
      <div className="flex items-start gap-2">
        <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-emerald-500/15 border border-emerald-500/25">
          <Leaf className="h-3.5 w-3.5 text-emerald-400" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <p className="text-xs font-semibold text-foreground">Interactive RAG</p>
            <InfoTip text={RAG_METHOD} />
          </div>
          <p className="text-[10px] text-muted-foreground">
            This query · separate from Document Processing
          </p>
        </div>
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2">
        <div className="rounded-lg border border-border/40 bg-background/40 px-2 py-1.5">
          <p className="text-[10px] text-muted-foreground">CO₂e / query</p>
          <p className="text-xs font-semibold tabular-nums">
            {fmtQueryG(carbon.estimated_gco2e)}
          </p>
        </div>
        <div className="rounded-lg border border-border/40 bg-background/40 px-2 py-1.5">
          <p className="text-[10px] text-muted-foreground">Energy</p>
          <p className="text-xs font-semibold tabular-nums">
            {(() => {
              const wh =
                carbon.estimated_energy_wh != null
                  ? Number(carbon.estimated_energy_wh)
                  : carbon.estimated_energy_kwh != null
                    ? Number(carbon.estimated_energy_kwh) * 1000
                    : null
              if (wh == null || !Number.isFinite(wh)) return "—"
              if (wh < 0.01) return `${wh.toFixed(4)} Wh`
              if (wh < 1) return `${wh.toFixed(3)} Wh`
              return `${wh.toFixed(2)} Wh`
            })()}
          </p>
        </div>
        <div className="rounded-lg border border-border/40 bg-background/40 px-2 py-1.5">
          <p className="text-[10px] text-muted-foreground">Grid intensity</p>
          <p
            className="text-xs font-semibold tabular-nums truncate"
            title={fmtIntensity(carbon.grid_intensity_gco2_kwh)}
          >
            {fmtIntensity(carbon.grid_intensity_gco2_kwh)}
          </p>
        </div>
      </div>
      <Collapsible className="mt-2">
        <CollapsibleTrigger className="group flex w-full items-center justify-between rounded-md px-1 py-1 text-[11px] text-muted-foreground hover:text-foreground">
          <span>Stage breakdown</span>
          <ChevronDown className="h-3.5 w-3.5 transition-transform group-data-[state=open]:rotate-180" />
        </CollapsibleTrigger>
        <CollapsibleContent className="mt-1 space-y-1 px-1">
          {[
            ["Query embedding", stages.query_embedding_gco2e],
            ["Retrieval", stages.retrieval_gco2e],
            ["LLM inference", llmG],
          ].map(([label, value]) => (
            <div
              key={String(label)}
              className="flex items-center justify-between text-[11px] text-muted-foreground"
            >
              <span>{label}</span>
              <span className="tabular-nums text-foreground/90">
                {fmtQueryG(value as number | undefined)}
              </span>
            </div>
          ))}
        </CollapsibleContent>
      </Collapsible>
    </div>
  )
}
