"use client"

import { useMemo, useState } from "react"
import { Card } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import type { CampaignBundle } from "@/lib/benchmark-types"
import {
  alignedQuestions,
  computeDelta,
  runByModel,
  sentimentClass,
  unionModels,
} from "@/lib/benchmark-compare"
import { fmtMs, fmtNum, fmtUsd } from "@/lib/benchmark-campaigns"
import { cn } from "@/lib/utils"

function MetricDiff({
  label,
  a,
  b,
  lowerIsBetter,
  format,
}: {
  label: string
  a: number | null | undefined
  b: number | null | undefined
  lowerIsBetter: boolean
  format: (v: number | null | undefined) => string
}) {
  const av = a == null ? null : Number(a)
  const bv = b == null ? null : Number(b)
  const { abs, pct, sentiment } = computeDelta(
    Number.isFinite(av as number) ? av : null,
    Number.isFinite(bv as number) ? bv : null,
    lowerIsBetter,
  )
  return (
    <div className="rounded-md border border-border/40 bg-black/25 px-2.5 py-2">
      <p className="text-[9px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1 text-[11px] font-mono tabular-nums text-foreground">
        {format(av)} → {format(bv)}
      </p>
      <p className={cn("mt-0.5 text-[11px] font-mono", sentimentClass(sentiment))}>
        {abs == null
          ? "—"
          : `${abs < 0 ? "↓" : abs > 0 ? "↑" : "→"} ${pct == null ? "—" : `${fmtNum(Math.abs(pct), 1)}%`}`}
      </p>
    </div>
  )
}

export function BenchmarkCompareQuestions({
  baseline,
  comparison,
}: {
  baseline: CampaignBundle
  comparison: CampaignBundle
}) {
  const questions = useMemo(
    () => alignedQuestions(baseline, comparison),
    [baseline, comparison],
  )
  const models = useMemo(
    () => unionModels(baseline, comparison),
    [baseline, comparison],
  )
  const [qid, setQid] = useState(questions[0]?.question || "")

  const selected = questions.find((q) => q.question === qid) || questions[0]

  return (
    <Card className="p-6 bg-gradient-to-br from-card to-card/50 border-border/50">
      <div className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-4 mb-5">
        <div>
          <h3 className="text-lg font-semibold">Question-level diff</h3>
          <p className="text-xs text-muted-foreground mt-1 max-w-2xl">
            Pick a question to compare every model run across both campaigns. Highlighted
            deltas use the same improve / regress coloring as KPI cards.
          </p>
        </div>
        <div className="w-full lg:w-[420px]">
          <label className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground mb-1.5 block">
            Question
          </label>
          <Select value={selected?.question || ""} onValueChange={setQid}>
            <SelectTrigger className="bg-card/60 border-border/60">
              <SelectValue placeholder="Select a question" />
            </SelectTrigger>
            <SelectContent>
              {questions.map((q, i) => (
                <SelectItem key={q.question} value={q.question}>
                  {String(i + 1).padStart(2, "0")}. {q.question}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {!selected ? (
        <p className="text-sm text-muted-foreground">No overlapping questions.</p>
      ) : (
        <div className="space-y-4">
          <p className="text-sm font-medium text-foreground">{selected.question}</p>
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <div className="rounded-lg border border-border/50 bg-black/20 p-4">
              <p className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground mb-3">
                Campaign A
              </p>
              <div className="space-y-3">
                {models.map((model) => {
                  const run = runByModel(selected.a, model)
                  return (
                    <div
                      key={`a-${model}`}
                      className="rounded-md border border-border/40 bg-card/40 p-3"
                    >
                      <p className="text-sm font-semibold mb-2">{model}</p>
                      <div className="grid grid-cols-2 gap-1.5 text-[11px] font-mono text-muted-foreground">
                        <span>Lat {fmtMs(run?.latency_ms)}</span>
                        <span>TTFT {fmtMs(run?.ttft_ms)}</span>
                        <span>Prompt {fmtNum(run?.prompt_tokens, 0)}</span>
                        <span>Compl {fmtNum(run?.completion_tokens, 0)}</span>
                        <span>Cost {fmtUsd(run?.estimated_api_cost_usd, 5)}</span>
                        <span>
                          CO₂e{" "}
                          {run?.estimated_co2e_g == null
                            ? "—"
                            : `${fmtNum(run.estimated_co2e_g, 3)} g`}
                        </span>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>

            <div className="rounded-lg border border-border/50 bg-black/20 p-4">
              <p className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground mb-3">
                Campaign B · deltas vs A
              </p>
              <div className="space-y-3">
                {models.map((model) => {
                  const aRun = runByModel(selected.a, model)
                  const bRun = runByModel(selected.b, model)
                  return (
                    <div
                      key={`b-${model}`}
                      className="rounded-md border border-border/40 bg-card/40 p-3"
                    >
                      <p className="text-sm font-semibold mb-2">{model}</p>
                      <div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5">
                        <MetricDiff
                          label="Latency"
                          a={aRun?.latency_ms}
                          b={bRun?.latency_ms}
                          lowerIsBetter
                          format={(v) => fmtMs(v)}
                        />
                        <MetricDiff
                          label="TTFT"
                          a={aRun?.ttft_ms}
                          b={bRun?.ttft_ms}
                          lowerIsBetter
                          format={(v) => fmtMs(v)}
                        />
                        <MetricDiff
                          label="Prompt tok"
                          a={aRun?.prompt_tokens}
                          b={bRun?.prompt_tokens}
                          lowerIsBetter
                          format={(v) => fmtNum(v, 0)}
                        />
                        <MetricDiff
                          label="Completion tok"
                          a={aRun?.completion_tokens}
                          b={bRun?.completion_tokens}
                          lowerIsBetter
                          format={(v) => fmtNum(v, 0)}
                        />
                        <MetricDiff
                          label="Cost"
                          a={aRun?.estimated_api_cost_usd}
                          b={bRun?.estimated_api_cost_usd}
                          lowerIsBetter
                          format={(v) => fmtUsd(v, 5)}
                        />
                        <MetricDiff
                          label="Energy"
                          a={aRun?.estimated_energy_wh}
                          b={bRun?.estimated_energy_wh}
                          lowerIsBetter
                          format={(v) =>
                            v == null ? "—" : `${fmtNum(v, 3)} Wh`
                          }
                        />
                        <MetricDiff
                          label="CO₂e"
                          a={aRun?.estimated_co2e_g}
                          b={bRun?.estimated_co2e_g}
                          lowerIsBetter
                          format={(v) =>
                            v == null ? "—" : `${fmtNum(v, 3)} g`
                          }
                        />
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        </div>
      )}
    </Card>
  )
}
