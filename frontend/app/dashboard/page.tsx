"use client"

import dynamic from "next/dynamic"
import { motion } from "framer-motion"
import { Sidebar } from "@/components/sidebar"
import { TopBar } from "@/components/top-bar"
import { GuestOwnerGate } from "@/components/guest-owner-gate"
import { KPICard } from "@/components/kpi-card"
import { DocumentHistory } from "@/components/document-history"
import { useEffect, useState } from "react"
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
import { cn } from "@/lib/utils"
import { DashboardChartsSkeleton } from "@/components/loading-skeletons"
import { useFinalizedMetrics } from "@/hooks/use-finalized-metrics"
import { useHistoricalAnalytics } from "@/hooks/use-historical-analytics"
import type { RangeKey } from "@/lib/historical-analytics-store"
import { fmtG, fmtIntensity, fmtPct } from "@/lib/job-results-metrics"
import { isGuestMode } from "@/lib/guest-session"

const DashboardCharts = dynamic(() => import("@/components/dashboard-charts"), {
  ssr: false,
  loading: () => <DashboardChartsSkeleton />,
})

type ViewMode = "latest" | "historical"

function fmt(value: number | undefined | null, digits = 2) {
  if (value == null || Number.isNaN(Number(value))) return "—"
  return Number(value).toFixed(digits)
}

export default function Dashboard() {
  const [view, setView] = useState<ViewMode>("latest")
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

  // Layer 2 — Historical Analytics (signed-in Owners only)
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
    if (view !== "historical") return
    void refreshHist(true)
  }, [personaReady, isGuest, view, range, customStart, customEnd, refreshHist])

  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState === "visible") {
        void refreshLatest(false)
        if (!isGuestMode() && view === "historical") void refreshHist(false)
      }
    }
    document.addEventListener("visibilitychange", onVis)
    return () => document.removeEventListener("visibilitychange", onVis)
  }, [refreshLatest, refreshHist, view])

  // Guests only have latest — keep view locked
  useEffect(() => {
    if (personaReady && isGuest && view !== "latest") setView("latest")
  }, [personaReady, isGuest, view])

  const histSparse = (stats?.point_count ?? stats?.carbon_trend?.length ?? 0) < 2
  const histEmpty =
    stats?.empty_state_message ||
    "More analytics will appear as additional documents are processed."

  const showHistorical = personaReady && !isGuest && view === "historical"
  const loading = showHistorical ? histLoading && !stats : latestLoading && !metrics

  const kpis = showHistorical
    ? [
        {
          title: "Optimized Emissions",
          value: stats ? fmt(stats.total_carbon_consumed) : loading ? "…" : "—",
          unit: "g CO₂e",
        },
        {
          title: "Baseline Pipeline",
          value: stats ? fmt(stats.total_baseline_carbon) : loading ? "…" : "—",
          unit: "g CO₂e",
        },
        {
          title: "Carbon Saved",
          value: stats ? fmt(stats.total_carbon_saved) : loading ? "…" : "—",
          unit: "g CO₂e",
        },
        {
          title: "Efficiency",
          value: stats ? fmt(stats.avg_efficiency, 1) : loading ? "…" : "—",
          unit: "%",
        },
      ]
    : [
        {
          title: "Optimized Emissions",
          value: metrics ? fmt(metrics.optimizedG) : loading ? "…" : "—",
          unit: "g CO₂e",
        },
        {
          title: "Baseline Pipeline",
          value: metrics ? fmt(metrics.baselineG) : loading ? "…" : "—",
          unit: "g CO₂e",
        },
        {
          title: "Carbon Saved",
          value: metrics ? fmt(metrics.savedG) : loading ? "…" : "—",
          unit: "g CO₂e",
        },
        {
          title: "Efficiency",
          value: metrics ? fmt(metrics.reductionPct, 1) : loading ? "…" : "—",
          unit: "%",
        },
      ]

  const icons = [Leaf, Scale, TrendingDown, Gauge]

  return (
    <GuestOwnerGate>
      <div className="flex">
        <Sidebar />
        <div className="flex-1 min-w-0">
          <TopBar />
          <main className="p-8">
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
              <div className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-4 mb-6">
                <div>
                  <h1 className="text-3xl font-bold mb-2">Dashboard & Analytics</h1>
                  <p className="text-muted-foreground">
                    {!personaReady
                      ? "Loading dashboard…"
                      : showHistorical
                        ? "Sum of every completed job in the selected range for this account."
                        : "Finalized metrics from your most recent completed job — same numbers as Results."}
                  </p>
                </div>

                {personaReady && !isGuest ? (
                  <div
                    className="inline-flex rounded-md border border-border/60 bg-card/70 p-1 backdrop-blur-sm"
                    role="tablist"
                    aria-label="Analytics view"
                  >
                    <button
                      type="button"
                      role="tab"
                      aria-selected={view === "latest"}
                      data-testid="dashboard-view-latest"
                      onClick={() => setView("latest")}
                      className={cn(
                        "px-3.5 py-1.5 text-sm font-medium rounded transition-colors",
                        view === "latest"
                          ? "bg-primary text-primary-foreground"
                          : "text-muted-foreground hover:text-foreground",
                      )}
                    >
                      Latest job
                    </button>
                    <button
                      type="button"
                      role="tab"
                      aria-selected={view === "historical"}
                      data-testid="dashboard-view-historical"
                      onClick={() => setView("historical")}
                      className={cn(
                        "px-3.5 py-1.5 text-sm font-medium rounded transition-colors",
                        view === "historical"
                          ? "bg-primary text-primary-foreground"
                          : "text-muted-foreground hover:text-foreground",
                      )}
                    >
                      Historical
                    </button>
                  </div>
                ) : null}
              </div>

              {/* Historical range controls — only when Historical is active */}
              {showHistorical ? (
                <Card className="p-4 border-border/50 bg-card/70 backdrop-blur-sm mb-6 w-full lg:w-auto lg:inline-flex">
                  <div className="flex flex-col sm:flex-row gap-3 sm:items-end">
                    <div className="space-y-1.5 min-w-[180px]">
                      <Label className="text-xs text-muted-foreground">Range</Label>
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

              {/* Single analytics section */}
              <p className="text-xs uppercase tracking-wide text-muted-foreground mb-3">
                {showHistorical ? "Historical analytics" : "Latest job snapshot"}
                {showHistorical && stats ? (
                  <span className="normal-case tracking-normal ml-2 text-muted-foreground/80">
                    · {stats.total_docs} document{stats.total_docs === 1 ? "" : "s"} · range{" "}
                    {stats.range}
                  </span>
                ) : null}
                {!showHistorical && jobId ? (
                  <span className="normal-case tracking-normal ml-2 text-muted-foreground/80">
                    · {jobId.slice(0, 8)} · rev {revision}
                    {updatedAt ? ` · ${updatedAt.slice(0, 19)}` : ""}
                  </span>
                ) : null}
              </p>

              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-4">
                {kpis.map((kpi, i) => {
                  const Icon = icons[i]
                  return (
                    <KPICard
                      key={`${view}-${kpi.title}`}
                      title={kpi.title}
                      value={kpi.value}
                      unit={kpi.unit}
                      icon={Icon}
                      delay={i * 0.05}
                    />
                  )
                })}
              </div>

              {!showHistorical && metrics ? (
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
              ) : null}
              {!showHistorical && !metrics && !loading ? (
                <p className="text-xs text-muted-foreground mb-8">
                  Process a document to populate the latest job snapshot.
                </p>
              ) : null}
              {showHistorical && stats && stats.total_docs > 1 ? (
                <p className="text-xs text-muted-foreground mb-8">
                  Totals sum {stats.total_docs} completed jobs — not the same as a single latest job.
                </p>
              ) : showHistorical ? (
                <div className="mb-8" />
              ) : null}

              {/* Single charts slot — no duplicate skeletons */}
              {loading ? (
                <DashboardChartsSkeleton />
              ) : showHistorical ? (
                <DashboardCharts
                  carbonTrend={stats?.carbon_trend || []}
                  energyTrend={stats?.energy_trend || []}
                  sparse={histSparse}
                  emptyMessage={histEmpty}
                />
              ) : metrics ? (
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
                  sparse
                  emptyMessage="Latest job — identical metrics object fields as Results."
                />
              ) : null}

              {personaReady && !isGuest ? (
                <div className="mt-8 mb-8">
                  <DocumentHistory />
                </div>
              ) : null}

              {!showHistorical && metrics ? (
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
