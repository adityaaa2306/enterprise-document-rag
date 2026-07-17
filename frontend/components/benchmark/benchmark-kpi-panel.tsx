"use client"

import { useMemo, useState } from "react"
import { motion } from "framer-motion"
import type { LucideIcon } from "lucide-react"
import {
  DollarSign,
  FlaskConical,
  ListChecks,
  Sparkles,
  Timer,
} from "lucide-react"
import { Card } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import type { CampaignBundle, ModelChartRow } from "@/lib/benchmark-types"
import {
  displayParticipantName,
  fmtMs,
  fmtNum,
  fmtUsd,
} from "@/lib/benchmark-campaigns"
import { cn } from "@/lib/utils"

type KpiKey = "runtime" | "cost" | "questions" | "models" | "version"

type KpiDef = {
  key: KpiKey
  title: string
  value: string | number
  unit?: string
  icon: LucideIcon
  hint: string
}

function DistributionRows({
  rows,
  metric,
  format,
}: {
  rows: ModelChartRow[]
  metric: keyof ModelChartRow
  format: (v: number | null | undefined) => string
}) {
  return (
    <div className="space-y-2">
      {rows.map((r) => {
        const raw = r[metric]
        const num = typeof raw === "number" ? raw : null
        const max = Math.max(
          ...rows.map((x) => {
            const v = x[metric]
            return typeof v === "number" ? v : 0
          }),
          1,
        )
        const pct = num == null ? 0 : (num / max) * 100
        return (
          <div key={r.model}>
            <div className="flex items-center justify-between text-xs mb-1">
              <span className="font-medium text-foreground">
                {displayParticipantName(r.model)}
              </span>
              <span className="font-mono text-muted-foreground tabular-nums">
                {format(num)}
              </span>
            </div>
            <div className="h-1.5 rounded-full bg-white/5 overflow-hidden">
              <div
                className="h-full rounded-full bg-emerald-400/70 transition-all duration-500"
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}

export function BenchmarkKpiPanel({ bundle }: { bundle: CampaignBundle }) {
  const [open, setOpen] = useState<KpiKey | null>(null)
  const dash = bundle.dashboard
  const totals = dash.totals
  const rows = dash.table?.per_model || []

  const totalRuns = useMemo(
    () => rows.reduce((acc, r) => acc + (r.n_runs || 0), 0),
    [rows],
  )

  const kpis: KpiDef[] = [
    {
      key: "runtime",
      title: "Total runtime",
      value: fmtNum(totals?.total_runtime_sec, 1),
      unit: "s",
      icon: Timer,
      hint: "Click for latency distribution",
    },
    {
      key: "cost",
      title: "Total API cost",
      value: fmtUsd(totals?.total_api_cost_usd, 4).replace("$", ""),
      unit: "USD",
      icon: DollarSign,
      hint: "Click for cost breakdown",
    },
    {
      key: "questions",
      title: "Questions",
      value: totals?.questions ?? bundle.config.question_count ?? "—",
      icon: ListChecks,
      hint: "Click for run counts",
    },
    {
      key: "models",
      title: "Models",
      value: bundle.metadata.models?.length ?? "—",
      icon: Sparkles,
      hint: "Click for per-model snapshot",
    },
    {
      key: "version",
      title: "Benchmark version",
      value: bundle.metadata.benchmark_version,
      icon: FlaskConical,
      hint: "Click for campaign versions",
    },
  ]

  const active = kpis.find((k) => k.key === open) || null

  return (
    <>
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-5 gap-4">
        {kpis.map((kpi, i) => {
          const Icon = kpi.icon
          return (
            <motion.button
              key={kpi.key}
              type="button"
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.03 * i, duration: 0.4 }}
              whileHover={{ y: -3 }}
              onClick={() => setOpen(kpi.key)}
              className="text-left"
            >
              <Card
                className={cn(
                  "p-6 h-full bg-gradient-to-br from-card to-card/50 border-border/50",
                  "hover:border-emerald-500/35 transition-colors cursor-pointer",
                  "focus-within:ring-2 focus-within:ring-emerald-500/30",
                )}
              >
                <div className="flex items-start justify-between mb-3">
                  <div>
                    <p className="text-sm text-muted-foreground mb-2">{kpi.title}</p>
                    <div className="flex items-baseline gap-2">
                      <p className="text-3xl font-bold text-foreground">{kpi.value}</p>
                      {kpi.unit ? (
                        <span className="text-sm text-muted-foreground">{kpi.unit}</span>
                      ) : null}
                    </div>
                  </div>
                  <div className="w-10 h-10 rounded-lg bg-primary/20 flex items-center justify-center">
                    <Icon className="w-5 h-5 text-primary" />
                  </div>
                </div>
                <p className="text-[11px] text-muted-foreground/80">{kpi.hint}</p>
              </Card>
            </motion.button>
          )
        })}
      </div>

      <Dialog open={!!open} onOpenChange={(v) => !v && setOpen(null)}>
        <DialogContent className="sm:max-w-lg bg-card border-border">
          <DialogHeader>
            <DialogTitle>{active?.title || "KPI detail"}</DialogTitle>
            <DialogDescription>
              Supporting metrics from stored campaign artifacts — no live regeneration.
            </DialogDescription>
          </DialogHeader>

          {open === "runtime" ? (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">
                Campaign wall time:{" "}
                <span className="text-foreground font-medium">
                  {fmtNum(totals?.total_runtime_sec, 2)} s
                </span>
              </p>
              <DistributionRows
                rows={rows}
                metric="avg_latency_ms"
                format={(v) => fmtMs(v)}
              />
              <p className="text-xs text-muted-foreground">
                Bars show average latency by model. p50 / p95 available in the Performance
                charts.
              </p>
            </div>
          ) : null}

          {open === "cost" ? (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">
                Total estimated spend:{" "}
                <span className="text-foreground font-medium">
                  {fmtUsd(totals?.total_api_cost_usd, 5)}
                </span>
              </p>
              <DistributionRows
                rows={rows}
                metric="total_estimated_api_cost_usd"
                format={(v) => fmtUsd(v, 5)}
              />
              <div className="grid grid-cols-2 gap-2 text-xs">
                {rows.map((r) => (
                  <div
                    key={r.model}
                    className="rounded-md border border-border/50 bg-black/20 px-3 py-2"
                  >
                    <p className="font-medium text-foreground">
                      {displayParticipantName(r.model)}
                    </p>
                    <p className="text-muted-foreground mt-1">
                      avg/q {fmtUsd(r.avg_estimated_api_cost_usd, 5)}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {open === "questions" ? (
            <div className="space-y-3 text-sm">
              <p>
                Questions in suite:{" "}
                <span className="font-medium text-foreground">
                  {totals?.questions ?? bundle.config.question_count}
                </span>
              </p>
              <p>
                Total model runs:{" "}
                <span className="font-medium text-foreground">{totalRuns}</span>
              </p>
              <ul className="space-y-1.5 text-muted-foreground">
                {rows.map((r) => (
                  <li key={r.model}>
                    {displayParticipantName(r.model)}: {r.n_ok ?? 0} ok /{" "}
                    {r.n_runs ?? 0} runs
                    {(r.n_failed || 0) > 0 ? ` (${r.n_failed} failed)` : ""}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {open === "models" ? (
            <div className="space-y-2">
              {rows.map((r) => (
                <div
                  key={r.model}
                  className="rounded-md border border-border/50 bg-black/20 px-3 py-2.5 text-xs"
                >
                  <p className="font-semibold text-sm text-foreground mb-1">
                    {displayParticipantName(r.model)}
                  </p>
                  <p className="text-muted-foreground font-mono tabular-nums">
                    {fmtMs(r.avg_latency_ms)} · {fmtNum(r.avg_tokens_per_sec, 1)} tok/s ·{" "}
                    {fmtUsd(r.total_estimated_api_cost_usd, 5)} ·{" "}
                    {fmtNum(r.avg_estimated_co2e_g, 3)} g
                  </p>
                </div>
              ))}
            </div>
          ) : null}

          {open === "version" ? (
            <dl className="grid grid-cols-1 gap-2 text-sm">
              <Row k="Benchmark version" v={bundle.metadata.benchmark_version} />
              <Row k="Retrieval version" v={bundle.metadata.retrieval_version} />
              <Row k="Prompt version" v={bundle.metadata.prompt_version} />
              <Row k="Suite" v={bundle.metadata.suite} />
              <Row k="Document ID" v={bundle.metadata.document_id} />
              <Row
                k="Dry run"
                v={bundle.metadata.dry_run ? "yes" : "no"}
              />
            </dl>
          ) : null}
        </DialogContent>
      </Dialog>
    </>
  )
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-md border border-border/40 bg-black/20 px-3 py-2">
      <dt className="text-muted-foreground">{k}</dt>
      <dd className="font-mono text-foreground text-right break-all">{v || "—"}</dd>
    </div>
  )
}
