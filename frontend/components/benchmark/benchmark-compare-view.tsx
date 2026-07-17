"use client"

import dynamic from "next/dynamic"
import { useMemo } from "react"
import { motion } from "framer-motion"
import { AlertTriangle, CheckCircle2, FileJson, FileText } from "lucide-react"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { BenchmarkCompareKpis } from "@/components/benchmark/benchmark-compare-kpis"
import { BenchmarkCompareTable } from "@/components/benchmark/benchmark-compare-table"
import { BenchmarkCompareQuestions } from "@/components/benchmark/benchmark-compare-questions"
import { BenchmarkCompareTimeline } from "@/components/benchmark/benchmark-compare-timeline"
import { BenchmarkAnalyticsSkeleton } from "@/components/benchmark/benchmark-analytics-skeleton"
import type { CampaignBundle, CampaignIndexEntry } from "@/lib/benchmark-types"
import {
  aggregateCampaign,
  buildEvolutionSummaryClean,
  buildExportPayload,
  buildKpiDeltas,
  buildModelDeltaRows,
  checkMethodology,
  downloadText,
  exportToMarkdown,
  formatPct,
  sentimentClass,
} from "@/lib/benchmark-compare"
import { fmtDate, fmtMs, fmtNum, fmtUsd } from "@/lib/benchmark-campaigns"
import { cn } from "@/lib/utils"

const BenchmarkCompareCharts = dynamic(
  () => import("@/components/benchmark/benchmark-compare-charts"),
  {
    ssr: false,
    loading: () => <BenchmarkAnalyticsSkeleton />,
  },
)

function fmtKpiSide(key: string, v: number | null): string {
  if (v == null) return "—"
  switch (key) {
    case "avg_latency_ms":
    case "avg_ttft_ms":
      return fmtMs(v)
    case "total_api_cost_usd":
      return fmtUsd(v, 4)
    case "avg_tokens_per_sec":
      return `${fmtNum(v, 1)} tok/s`
    case "avg_estimated_energy_wh":
      return `${fmtNum(v, 3)} Wh`
    case "avg_estimated_co2e_g":
      return `${fmtNum(v, 3)} g`
    case "total_tokens":
      return Math.round(v).toLocaleString()
    default:
      return fmtNum(v, 2)
  }
}

export function BenchmarkCompareView({
  baseline,
  comparison,
  campaigns,
  timelineBundles,
  loading,
}: {
  baseline: CampaignBundle | null
  comparison: CampaignBundle | null
  campaigns: CampaignIndexEntry[]
  timelineBundles: Record<string, CampaignBundle | undefined>
  loading?: boolean
}) {
  const computed = useMemo(() => {
    if (!baseline || !comparison) return null
    const aAgg = aggregateCampaign(baseline)
    const bAgg = aggregateCampaign(comparison)
    const deltas = buildKpiDeltas(aAgg, bAgg)
    const methodology = checkMethodology(baseline, comparison)
    const modelRows = buildModelDeltaRows(baseline, comparison)
    const summary = buildEvolutionSummaryClean(baseline, comparison, deltas)
    return { aAgg, bAgg, deltas, methodology, modelRows, summary }
  }, [baseline, comparison])

  if (loading && (!baseline || !comparison)) {
    return <BenchmarkAnalyticsSkeleton />
  }

  if (!baseline || !comparison || !computed) {
    return (
      <Card className="p-8 border-border/50 bg-card/40 text-sm text-muted-foreground">
        Select a baseline and comparison campaign to begin.
      </Card>
    )
  }

  const { deltas, methodology, modelRows, summary } = computed
  const compatible = methodology.every((m) => m.match)
  const labelA = baseline.index.label || baseline.index.campaign_id
  const labelB = comparison.index.label || comparison.index.campaign_id

  const onExportJson = () => {
    const payload = buildExportPayload(baseline, comparison)
    downloadText(
      `compare_${baseline.index.campaign_id}_vs_${comparison.index.campaign_id}.json`,
      JSON.stringify(payload, null, 2),
      "application/json",
    )
  }

  const onExportMd = () => {
    const payload = buildExportPayload(baseline, comparison)
    downloadText(
      `compare_${baseline.index.campaign_id}_vs_${comparison.index.campaign_id}.md`,
      exportToMarkdown(payload),
      "text/markdown",
    )
  }

  return (
    <div className="space-y-10">
      {/* Header actions */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <Badge variant="outline" className="border-border/60 text-foreground">
            A · {labelA}
          </Badge>
          <span>→</span>
          <Badge
            variant="outline"
            className="border-emerald-500/30 text-emerald-300"
          >
            B · {labelB}
          </Badge>
          <span className="font-mono opacity-70">
            {fmtDate(baseline.metadata.timestamp_utc)} →{" "}
            {fmtDate(comparison.metadata.timestamp_utc)}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onExportMd}
            className="gap-1.5"
          >
            <FileText className="w-3.5 h-3.5" />
            Export Markdown
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onExportJson}
            className="gap-1.5"
          >
            <FileJson className="w-3.5 h-3.5" />
            Export JSON
          </Button>
        </div>
      </div>

      {/* Methodology warning */}
      <Card
        className={cn(
          "p-4 border",
          compatible
            ? "border-border/50 bg-card/40"
            : "border-amber-500/30 bg-amber-500/5",
        )}
      >
        <div className="flex items-start gap-3">
          {compatible ? (
            <CheckCircle2 className="w-4 h-4 text-emerald-300/80 mt-0.5 shrink-0" />
          ) : (
            <AlertTriangle className="w-4 h-4 text-amber-300 mt-0.5 shrink-0" />
          )}
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-foreground">
              {compatible
                ? "Methodology fields match — campaigns are directly comparable."
                : "Methodology differs — comparisons may not be directly comparable."}
            </p>
            <div className="mt-2 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
              {methodology.map((m) => (
                <div
                  key={m.field}
                  className="rounded-md border border-border/40 bg-black/20 px-2.5 py-2 text-[11px]"
                >
                  <p className="text-muted-foreground uppercase tracking-wide mb-1">
                    {m.label}
                  </p>
                  <p className="font-mono text-foreground break-all">
                    {m.a}
                    {!m.match ? (
                      <span className="text-amber-200"> ≠ {m.b}</span>
                    ) : (
                      <span className="text-muted-foreground"> = {m.b}</span>
                    )}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </Card>

      {/* Executive comparison */}
      <section className="space-y-4">
        <h2 className="text-sm font-medium uppercase tracking-[0.14em] text-muted-foreground">
          Executive comparison
        </h2>
        <Card className="p-6 bg-gradient-to-br from-card to-card/40 border-border/50">
          <div className="flex flex-col md:flex-row md:items-center gap-4 md:gap-8 mb-6">
            <div className="min-w-0">
              <p className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
                Benchmark A
              </p>
              <p className="text-base font-semibold truncate">{labelA}</p>
              <p className="text-xs text-muted-foreground font-mono mt-0.5">
                v{baseline.metadata.benchmark_version} ·{" "}
                {fmtDate(baseline.metadata.timestamp_utc)}
              </p>
            </div>
            <div className="text-muted-foreground text-xl md:px-2">↓</div>
            <div className="min-w-0">
              <p className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
                Benchmark B
              </p>
              <p className="text-base font-semibold truncate text-emerald-300">
                {labelB}
              </p>
              <p className="text-xs text-muted-foreground font-mono mt-0.5">
                v{comparison.metadata.benchmark_version} ·{" "}
                {fmtDate(comparison.metadata.timestamp_utc)}
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
            {deltas.map((d) => (
              <div
                key={d.key}
                className="rounded-lg border border-border/45 bg-black/25 px-3 py-3"
              >
                <p className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground mb-2">
                  {d.label}
                </p>
                <p className="text-sm font-mono tabular-nums text-foreground">
                  {fmtKpiSide(d.key, d.a)} → {fmtKpiSide(d.key, d.b)}
                </p>
                <p
                  className={cn(
                    "mt-1.5 text-sm font-semibold tabular-nums",
                    sentimentClass(d.sentiment),
                  )}
                >
                  {d.pct == null
                    ? "—"
                    : `${d.abs != null && d.abs < 0 ? "↓" : d.abs != null && d.abs > 0 ? "↑" : "→"} ${formatPct(d.pct).replace(/^[+−]/, "")}`}
                </p>
              </div>
            ))}
          </div>
        </Card>
      </section>

      {/* KPI delta cards */}
      <section className="space-y-4">
        <h2 className="text-sm font-medium uppercase tracking-[0.14em] text-muted-foreground">
          KPI deltas
        </h2>
        <BenchmarkCompareKpis deltas={deltas} />
      </section>

      {/* Evolution summary */}
      <motion.section
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35 }}
      >
        <Card className="p-6 md:p-7 bg-gradient-to-br from-card to-card/40 border-border/50">
          <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-emerald-400/90 mb-2">
            Benchmark evolution
          </p>
          <h3 className="text-lg font-semibold tracking-tight mb-3">
            Did the system improve?
          </h3>
          <p className="text-sm text-muted-foreground leading-relaxed max-w-4xl">
            {summary}
          </p>
        </Card>
      </motion.section>

      <section>
        <BenchmarkCompareCharts
          baseline={baseline}
          comparison={comparison}
          labelA={labelA}
          labelB={labelB}
        />
      </section>

      <section>
        <BenchmarkCompareTable rows={modelRows} />
      </section>

      <section>
        <BenchmarkCompareQuestions baseline={baseline} comparison={comparison} />
      </section>

      <section className="pb-4">
        <BenchmarkCompareTimeline
          campaigns={campaigns}
          bundles={timelineBundles}
        />
      </section>
    </div>
  )
}
