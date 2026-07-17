"use client"

import { useState } from "react"
import { ChevronDown, Hash } from "lucide-react"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import type { QuestionExplorerItem, QuestionRun } from "@/lib/benchmark-types"
import {
  displayParticipantName,
  fmtMs,
  fmtNum,
  fmtUsd,
  shortHash,
} from "@/lib/benchmark-campaigns"
import { cn } from "@/lib/utils"

function ModelResponseCard({ run }: { run: QuestionRun }) {
  return (
    <div className="rounded-lg border border-border/45 bg-card/50 p-3.5 flex flex-col min-h-[220px]">
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <span className="text-sm font-semibold">
          {displayParticipantName(run.model)}
        </span>
        {run.ok ? (
          <Badge
            variant="outline"
            className="border-emerald-500/30 text-emerald-300 text-[10px]"
          >
            ok
          </Badge>
        ) : (
          <Badge
            variant="outline"
            className="border-red-500/30 text-red-300 text-[10px]"
          >
            failed
          </Badge>
        )}
        {run.participant_kind === "system_router" ||
        run.model === "intelligent-router" ? (
          <Badge
            variant="outline"
            className="border-border/50 text-muted-foreground text-[10px]"
          >
            system
          </Badge>
        ) : null}
        {run.model_returned ? (
          <span className="text-[10px] font-mono text-muted-foreground truncate max-w-[160px]">
            via {run.model_returned}
          </span>
        ) : null}
      </div>
      {run.routing?.reason_summary ? (
        <p className="text-[11px] text-muted-foreground mb-2 line-clamp-2">
          {String(run.routing.reason_summary)}
        </p>
      ) : null}

      <div className="grid grid-cols-2 gap-1.5 text-[11px] mb-3">
        <Metric label="Latency" value={fmtMs(run.latency_ms)} />
        <Metric label="TTFT" value={fmtMs(run.ttft_ms)} />
        <Metric
          label="Tokens"
          value={
            run.total_tokens == null
              ? "—"
              : `${run.prompt_tokens ?? "—"}→${run.completion_tokens ?? "—"}`
          }
        />
        <Metric label="tok/s" value={fmtNum(run.tokens_per_sec, 1)} />
        <Metric label="Cost" value={fmtUsd(run.estimated_api_cost_usd, 5)} />
        <Metric
          label="CO₂e"
          value={
            run.estimated_co2e_g == null
              ? "—"
              : `${fmtNum(run.estimated_co2e_g, 3)} g`
          }
        />
        <Metric
          label="Quality"
          value={
            (run.quality?.quality_score ?? run.quality_score) == null
              ? "—"
              : fmtNum(run.quality?.quality_score ?? run.quality_score, 1)
          }
        />
        <Metric
          label="Correct"
          value={
            (run.quality?.correctness ?? run.correctness) == null
              ? "—"
              : fmtNum(run.quality?.correctness ?? run.correctness, 1)
          }
        />
      </div>

      <div className="flex-1 rounded-md bg-black/25 border border-border/30 px-3 py-2.5 overflow-auto max-h-48">
        {run.error ? (
          <p className="text-xs text-red-300/90 font-mono whitespace-pre-wrap">
            {run.error}
          </p>
        ) : (
          <p className="text-sm text-muted-foreground leading-relaxed whitespace-pre-wrap">
            {run.answer?.trim() || "—"}
          </p>
        )}
      </div>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-black/25 px-2 py-1.5 border border-border/25">
      <p className="text-[9px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-0.5 font-mono text-[11px] text-foreground tabular-nums">{value}</p>
    </div>
  )
}

export function BenchmarkQuestionExplorer({
  questions,
}: {
  questions: QuestionExplorerItem[]
}) {
  const [openId, setOpenId] = useState<string | null>(
    questions.length ? `0-${questions[0].context_hash?.slice(0, 8)}` : null,
  )

  return (
    <Card className="p-6 bg-gradient-to-br from-card to-card/50 border-border/50">
      <div className="mb-5">
        <h3 className="text-lg font-semibold">Question explorer</h3>
        <p className="text-xs text-muted-foreground mt-1">
          Expand a question to compare every model side-by-side — same frozen context, different
          generations. Metrics and answers are loaded from stored artifacts only.
        </p>
      </div>

      <div className="space-y-2">
        {questions.map((q, idx) => {
          const id = `${idx}-${q.context_hash?.slice(0, 8)}`
          const open = openId === id
          return (
            <Collapsible
              key={id}
              open={open}
              onOpenChange={(v) => setOpenId(v ? id : null)}
            >
              <div className="rounded-lg border border-border/60 bg-black/20 overflow-hidden">
                <CollapsibleTrigger asChild>
                  <button
                    type="button"
                    className={cn(
                      "w-full flex items-start gap-3 px-4 py-3.5 text-left transition-colors",
                      "hover:bg-white/[0.03]",
                    )}
                  >
                    <span className="mt-0.5 text-[11px] font-mono text-muted-foreground w-6 shrink-0">
                      {String(idx + 1).padStart(2, "0")}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-foreground leading-snug">
                        {q.question}
                      </p>
                      <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground font-mono">
                        <span className="inline-flex items-center gap-1">
                          <Hash className="w-3 h-3" />
                          ctx {shortHash(q.context_hash)}
                        </span>
                        <span>prompt {shortHash(q.prompt_hash)}</span>
                        <span>{q.chunk_count ?? "—"} chunks</span>
                        <span>{(q.model_runs || []).length} models</span>
                      </div>
                    </div>
                    <ChevronDown
                      className={cn(
                        "w-4 h-4 mt-1 text-muted-foreground transition-transform duration-200 shrink-0",
                        open && "rotate-180",
                      )}
                    />
                  </button>
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <div className="border-t border-border/50 px-4 py-4 bg-black/30 space-y-4">
                    {q.reference_answer ? (
                      <div className="rounded-lg border border-border/45 bg-black/25 px-3.5 py-3">
                        <p className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1.5">
                          Reference answer
                        </p>
                        <p className="text-sm text-muted-foreground leading-relaxed whitespace-pre-wrap">
                          {q.reference_answer}
                        </p>
                      </div>
                    ) : null}
                    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
                      {(q.model_runs || []).map((run) => (
                        <ModelResponseCard
                          key={`${q.question}-${run.model}`}
                          run={run}
                        />
                      ))}
                    </div>
                  </div>
                </CollapsibleContent>
              </div>
            </Collapsible>
          )
        })}
      </div>
    </Card>
  )
}
