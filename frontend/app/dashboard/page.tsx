"use client"

import dynamic from "next/dynamic"
import { motion } from "framer-motion"
import { Sidebar } from "@/components/sidebar"
import { TopBar } from "@/components/top-bar"
import { apiFetch } from "@/lib/api"
import { KPICard } from "@/components/kpi-card"
import { DocumentHistory } from "@/components/document-history"
import { useCallback, useEffect, useMemo, useState } from "react"
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

const DashboardCharts = dynamic(() => import("@/components/dashboard-charts"), {
  ssr: false,
  loading: () => <DashboardChartsSkeleton />,
})

type RangeKey = "today" | "7d" | "30d" | "90d" | "custom"

interface TrendPoint {
  date: string
  date_iso?: string
  savings?: number
  carbon_saved?: number
  baseline?: number
  actual?: number
  efficiency?: number
  docs_processed?: number
}

interface EnergyPoint {
  date: string
  date_iso?: string
  energy_consumed_kwh?: number
  estimated_co2e?: number
  docs_processed?: number
}

interface DashboardStats {
  total_carbon_saved: number
  total_carbon_consumed: number
  total_baseline_carbon: number
  total_docs: number
  avg_efficiency: number
  carbon_trend: TrendPoint[]
  energy_trend: EnergyPoint[]
  range?: string
  start_date?: string | null
  end_date?: string | null
  point_count?: number
  empty_state_message?: string | null
}

function fmt(value: number | undefined | null, digits = 2) {
  if (value == null || Number.isNaN(Number(value))) return "—"
  return Number(value).toFixed(digits)
}

export default function Dashboard() {
  const [range, setRange] = useState<RangeKey>("30d")
  const [customStart, setCustomStart] = useState("")
  const [customEnd, setCustomEnd] = useState("")
  const [stats, setStats] = useState<DashboardStats>({
    total_carbon_saved: 0,
    total_carbon_consumed: 0,
    total_baseline_carbon: 0,
    total_docs: 0,
    avg_efficiency: 0,
    carbon_trend: [],
    energy_trend: [],
  })
  const [statsLoaded, setStatsLoaded] = useState(false)

  const queryString = useMemo(() => {
    const params = new URLSearchParams()
    params.set("range", range)
    if (range === "custom") {
      if (customStart) params.set("start_date", customStart)
      if (customEnd) params.set("end_date", customEnd)
    }
    return params.toString()
  }, [range, customStart, customEnd])

  const fetchStats = useCallback(async () => {
    try {
      const res = await apiFetch(`/dashboard-stats?${queryString}`)
      if (res.ok) {
        const data = await res.json()
        setStats({
          total_carbon_saved: Number(data.total_carbon_saved || 0),
          total_carbon_consumed: Number(data.total_carbon_consumed || 0),
          total_baseline_carbon: Number(data.total_baseline_carbon || 0),
          total_docs: Number(data.total_docs || 0),
          avg_efficiency: Number(data.avg_efficiency || 0),
          carbon_trend: Array.isArray(data.carbon_trend) ? data.carbon_trend : [],
          energy_trend: Array.isArray(data.energy_trend) ? data.energy_trend : [],
          range: data.range,
          start_date: data.start_date,
          end_date: data.end_date,
          point_count: data.point_count,
          empty_state_message: data.empty_state_message,
        })
      }
    } catch (e) {
      console.error("Failed to fetch dashboard stats", e)
    } finally {
      setStatsLoaded(true)
    }
  }, [queryString])

  useEffect(() => {
    fetchStats()
    const interval = setInterval(fetchStats, 10000)
    return () => clearInterval(interval)
  }, [fetchStats])

  const sparse = (stats.point_count ?? stats.carbon_trend.length) < 2
  const emptyMessage =
    stats.empty_state_message ||
    "More analytics will appear as additional documents are processed."

  return (
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
                  Actual vs baseline CO₂e from workflow energy × live Electricity Maps intensity.
                </p>
              </div>

              <Card className="p-4 border-border/50 bg-card/70 backdrop-blur-sm w-full lg:w-auto">
                <div className="flex flex-col sm:flex-row gap-3 sm:items-end">
                  <div className="space-y-1.5 min-w-[180px]">
                    <Label className="text-xs text-muted-foreground">Time Range</Label>
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
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
              <KPICard
                title="Estimated Optimized Emissions"
                value={fmt(stats.total_carbon_consumed)}
                unit="g CO₂e"
                icon={Leaf}
                delay={0}
              />
              <KPICard
                title="Estimated Baseline Pipeline"
                value={fmt(stats.total_baseline_carbon)}
                unit="g CO₂e"
                icon={Scale}
                delay={0.05}
              />
              <KPICard
                title="Estimated Carbon Saved"
                value={fmt(stats.total_carbon_saved)}
                unit="g CO₂e"
                icon={TrendingDown}
                delay={0.1}
              />
              <KPICard
                title="Efficiency"
                value={fmt(stats.avg_efficiency, 1)}
                unit="%"
                icon={Gauge}
                delay={0.15}
              />
            </div>

            {statsLoaded ? (
              <DashboardCharts
                carbonTrend={stats.carbon_trend}
                energyTrend={stats.energy_trend}
                sparse={sparse}
                emptyMessage={emptyMessage}
              />
            ) : (
              <DashboardChartsSkeleton />
            )}

            <div className="mb-8">
              <DocumentHistory />
            </div>
          </motion.div>
        </main>
      </div>
    </div>
  )
}
