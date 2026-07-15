"use client"

import dynamic from "next/dynamic"
import { motion } from "framer-motion"
import { Sidebar } from "@/components/sidebar"
import { TopBar } from "@/components/top-bar"
import { GuestOwnerGate } from "@/components/guest-owner-gate"
import { KPICard } from "@/components/kpi-card"
import { DocumentHistory } from "@/components/document-history"
import { useEffect, useMemo, useState } from "react"
import { Leaf, Scale, TrendingDown, Gauge } from "lucide-react"
import { Card } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { DashboardChartsSkeleton } from "@/components/loading-skeletons"
import { useFinalizedMetrics } from "@/hooks/use-finalized-metrics"
import { useHistoricalAnalytics } from "@/hooks/use-historical-analytics"
import type { RangeKey } from "@/lib/historical-analytics-store"
import { chartsFromFinalizedMetrics } from "@/lib/finalized-metrics-store"
import { fmtG, fmtIntensity, fmtPct } from "@/lib/job-results-metrics"
import { isGuestMode } from "@/lib/guest-session"

const DashboardCharts = dynamic(() => import("@/components/dashboard-charts"), {
  ssr: false,
  loading: () => <DashboardChartsSkeleton />,
})

function fmt(value: number | undefined | null, digits = 2) {
  if (value == null || Number.isNaN(Number(value))) return "—"
  return Number(value).toFixed(digits)
}

export default function Dashboard() {
  const [range, setRange] = useState<RangeKey>("30d")
  const [customStart, setCustomStart] = useState("")
  const [customEnd, setCustomEnd] = useState("")
  const [isGuest, setIsGuest] = useState(false)
  const [personaReady, setPersonaReady] = useState(false)

  useEffect(() => {
    const guest = isGuestMode()
    setIsGuest(guest)
    setPersonaReady(true)
  }, [])

  // Layer 1 — Latest Job Snapshot (same finalized metrics as Results)
  const {
    metrics,
    jobId,
    revision,
    updatedAt,
    syncKey,
    loading: latestLoading,
    refresh: refreshLatest,
  } = useFinalizedMetrics({ refreshOnMount: true })

  // Layer 2 — Historical Analytics (signed-in Owners only; never auto-fetch for guests)
  const {
    stats,
    loading: histLoading,
    refresh: refreshHist,
  } = useHistoricalAnalytics({
    range,
    customStart,
    customEnd,
    refreshOnMount: false,
  })

  useEffect(() => {
    if (!personaReady || isGuest) return
    void refreshHist(true)
  }, [personaReady, isGuest, range, customStart, customEnd, refreshHist])

  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState === "visible") {
        void refreshLatest(false)
        if (!isGuestMode()) void refreshHist(false)
      }
    }
    document.addEventListener("visibilitychange", onVis)
    return () => document.removeEventListener("visibilitychange", onVis)
  }, [refreshLatest, refreshHist])

  const latestCharts = useMemo(() => {
    if (!metrics) {
      return { modelBars: [] as ReturnType<typeof chartsFromFinalizedMetrics>["modelBars"] }
    }
    return chartsFromFinalizedMetrics(
      metrics,
      jobId ? `Job ${jobId.slice(0, 8)}` : "Latest job",
    )
  }, [metrics, jobId])

  const histSparse = (stats?.point_count ?? stats?.carbon_trend?.length ?? 0) < 2
  const histEmpty =
    stats?.empty_state_message ||
    "More analytics will appear as additional documents are processed."

  return (
    <GuestOwnerGate>
      <div className="flex">
        <Sidebar />
        <div className="flex-1 min-w-0">
          <TopBar />
          <main className="p-8">
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
              <div className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-4 mb-8">
                <div>
                  <h1 className="text-3xl font-bold mb-2">Dashboard & Analytics</h1>
                  <p className="text-muted-foreground">
                    {!personaReady
                      ? "Loading dashboard…"
                      : isGuest
                        ? "Latest job snapshot mirrors the same finalized metrics as Results."
                        : "Latest job mirrors Results. Historical analytics aggregate every completed job for this Owner."}
                  </p>
                </div>

                {personaReady && !isGuest ? (
                  <Card className="p-4 border-border/50 bg-card/70 backdrop-blur-sm w-full lg:w-auto">
                    <div className="flex flex-col sm:flex-row gap-3 sm:items-end">
                      <div className="space-y-1.5 min-w-[180px]">
                        <Label className="text-xs text-muted-foreground">
                          Historical range
                        </Label>
                        <Select value={range} onValueChange={(v) => setRange(v as RangeKey)}>
                          <SelectTrigger className="bg-background border-border">
                            <SelectValue placeholder="Select range" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="today">Today</SelectItem>
                            <SelectItem value="7d">Last 7 Days</SelectItem>
                            <SelectItem value="30d">Last 30 Days</SelectItem>
                            <SelectItem value="90d">Last 90 Days</SelectItem>
                            <SelectItem value="custom">Custom Range</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      {range === "custom" ? (
                        <>
                          <div className="space-y-1.5">
                            <Label className="text-xs text-muted-foreground">Start</Label>
                            <Input
                              type="date"
                              value={customStart}
                              onChange={(e) => setCustomStart(e.target.value)}
                              className="bg-background border-border"
                            />
                          </div>
                          <div className="space-y-1.5">
                            <Label className="text-xs text-muted-foreground">End</Label>
                            <Input
                              type="date"
                              value={customEnd}
                              onChange={(e) => setCustomEnd(e.target.value)}
                              className="bg-background border-border"
                            />
                          </div>
                        </>
                      ) : null}
                    </div>
                  </Card>
                ) : null}
              </div>

              {/* ── Layer 1: Latest Job Snapshot ── */}
              <p className="text-xs uppercase tracking-wide text-muted-foreground mb-3">
                Latest job snapshot
                {jobId ? (
                  <span className="normal-case tracking-normal ml-2 text-muted-foreground/80">
                    · {jobId.slice(0, 8)} · rev {revision}
                    {updatedAt ? ` · ${updatedAt.slice(0, 19)}` : ""}
                  </span>
                ) : null}
              </p>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-4">
                <KPICard
                  title="Estimated Optimized Emissions"
                  value={metrics ? fmt(metrics.optimizedG) : latestLoading ? "…" : "—"}
                  unit="g CO₂e"
                  icon={Leaf}
                  delay={0}
                />
                <KPICard
                  title="Estimated Baseline Pipeline"
                  value={metrics ? fmt(metrics.baselineG) : latestLoading ? "…" : "—"}
                  unit="g CO₂e"
                  icon={Scale}
                  delay={0.05}
                />
                <KPICard
                  title="Estimated Carbon Saved"
                  value={metrics ? fmt(metrics.savedG) : latestLoading ? "…" : "—"}
                  unit="g CO₂e"
                  icon={TrendingDown}
                  delay={0.1}
                />
                <KPICard
                  title="Efficiency"
                  value={metrics ? fmt(metrics.reductionPct, 1) : latestLoading ? "…" : "—"}
                  unit="%"
                  icon={Gauge}
                  delay={0.15}
                />
              </div>
              {metrics ? (
                <p className="text-xs text-muted-foreground mb-8">
                  Same as Results · {metrics.region} · {fmtIntensity(metrics.intensityGco2Kwh)} ·{" "}
                  {metrics.totalChunks} chunks · L{metrics.tierMix.light}/M
                  {metrics.tierMix.medium}/H{metrics.tierMix.heavy}
                  {syncKey ? (
                    <span className="sr-only" data-sync-key={syncKey}>
                      {syncKey}
                    </span>
                  ) : null}
                </p>
              ) : (
                <p className="text-xs text-muted-foreground mb-8">
                  Process a document to populate the latest job snapshot.
                </p>
              )}

              {/* Latest job model bars (same CompactJobMetrics.modelBars as Results) */}
              {metrics && latestCharts.modelBars.length > 0 ? (
                <div className="mb-8">
                  <DashboardCharts
                    carbonTrend={[
                      {
                        date: jobId ? `Job ${jobId.slice(0, 8)}` : "Latest",
                        baseline: metrics.baselineG,
                        actual: metrics.optimizedG,
                        carbon_saved: metrics.savedG,
                        efficiency: metrics.reductionPct,
                        docs_processed: 1,
                      },
                    ]}
                    energyTrend={[]}
                    modelBars={latestCharts.modelBars}
                    sparse
                    emptyMessage="Latest job — identical metrics object fields as Results."
                  />
                </div>
              ) : null}

              {/* ── Layer 2: Historical Analytics (signed-in only) ── */}
              {personaReady && !isGuest ? (
                <>
                  <p className="text-xs uppercase tracking-wide text-muted-foreground mb-3">
                    Historical analytics
                    {stats ? (
                      <span className="normal-case tracking-normal ml-2 text-muted-foreground/80">
                        · {stats.total_docs} document{stats.total_docs === 1 ? "" : "s"} · range{" "}
                        {stats.range}
                      </span>
                    ) : null}
                  </p>
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
                    <KPICard
                      title="Total Optimized Emissions"
                      value={stats ? fmt(stats.total_carbon_consumed) : histLoading ? "…" : "—"}
                      unit="g CO₂e"
                      icon={Leaf}
                      delay={0}
                    />
                    <KPICard
                      title="Total Baseline Pipeline"
                      value={stats ? fmt(stats.total_baseline_carbon) : histLoading ? "…" : "—"}
                      unit="g CO₂e"
                      icon={Scale}
                      delay={0.05}
                    />
                    <KPICard
                      title="Total Carbon Saved"
                      value={stats ? fmt(stats.total_carbon_saved) : histLoading ? "…" : "—"}
                      unit="g CO₂e"
                      icon={TrendingDown}
                      delay={0.1}
                    />
                    <KPICard
                      title="Average Efficiency"
                      value={stats ? fmt(stats.avg_efficiency, 1) : histLoading ? "…" : "—"}
                      unit="%"
                      icon={Gauge}
                      delay={0.15}
                    />
                  </div>

                  {stats || !histLoading ? (
                    <DashboardCharts
                      carbonTrend={stats?.carbon_trend || []}
                      energyTrend={stats?.energy_trend || []}
                      sparse={histSparse}
                      emptyMessage={histEmpty}
                    />
                  ) : (
                    <DashboardChartsSkeleton />
                  )}

                  <div className="mb-8">
                    <DocumentHistory />
                  </div>
                </>
              ) : null}

              {metrics ? (
                <p className="text-xs text-muted-foreground mt-2">
                  Latest fingerprint · Optimized {fmtG(metrics.optimizedG)} · Baseline{" "}
                  {fmtG(metrics.baselineG)} · Saved {fmtG(metrics.savedG)} ·{" "}
                  {fmtPct(metrics.reductionPct)}
                </p>
              ) : null}
            </motion.div>
          </main>
        </div>
      </div>
    </GuestOwnerGate>
  )
}
