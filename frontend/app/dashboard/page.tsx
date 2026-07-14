"use client"

import { motion } from "framer-motion"
import { Sidebar } from "@/components/sidebar"
import { TopBar } from "@/components/top-bar"
import { apiFetch } from "@/lib/api"
import { KPICard } from "@/components/kpi-card"
import { ChartCard } from "@/components/chart-card"
import { DocumentHistory } from "@/components/document-history"
import { useCallback, useEffect, useMemo, useState } from "react"
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
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

function CarbonTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  const row = payload[0]?.payload as TrendPoint
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2 text-xs shadow-xl">
      <p className="font-semibold mb-1">{label}</p>
      <p>Baseline CO₂: {fmt(row.baseline)} g</p>
      <p>Actual CO₂: {fmt(row.actual)} g</p>
      <p>Carbon Saved: {fmt(row.carbon_saved ?? row.savings)} g</p>
      <p>Efficiency: {fmt(row.efficiency, 1)}%</p>
    </div>
  )
}

function EnergyTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  const row = payload[0]?.payload as EnergyPoint
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2 text-xs shadow-xl">
      <p className="font-semibold mb-1">{label}</p>
      <p>Energy Consumed: {fmt(row.energy_consumed_kwh, 4)} kWh</p>
      <p>Estimated CO₂: {fmt(row.estimated_co2e)} g</p>
      <p>Documents Processed: {row.docs_processed ?? 0}</p>
    </div>
  )
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

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
              <ChartCard title="Daily Carbon Savings vs Baseline" delay={0.2}>
                {sparse ? (
                  <div className="space-y-4">
                    <p className="text-sm text-muted-foreground">{emptyMessage}</p>
                    {stats.carbon_trend.length > 0 ? (
                      <ResponsiveContainer width="100%" height={260}>
                        <BarChart data={stats.carbon_trend}>
                          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
                          <XAxis dataKey="date" stroke="rgba(255,255,255,0.45)" />
                          <YAxis stroke="rgba(255,255,255,0.45)" />
                          <Tooltip content={<CarbonTooltip />} />
                          <Legend />
                          <Bar dataKey="baseline" name="Baseline CO₂" fill="#64748b" radius={6} />
                          <Bar dataKey="actual" name="Actual CO₂" fill="#22c55e" radius={6} />
                          <Bar
                            dataKey="carbon_saved"
                            name="Carbon Saved"
                            fill="#3b82f6"
                            radius={6}
                          />
                        </BarChart>
                      </ResponsiveContainer>
                    ) : (
                      <div className="h-[260px] flex items-center justify-center text-sm text-muted-foreground">
                        No documents in this range yet.
                      </div>
                    )}
                  </div>
                ) : (
                  <ResponsiveContainer width="100%" height={300}>
                    <LineChart data={stats.carbon_trend}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
                      <XAxis dataKey="date" stroke="rgba(255,255,255,0.45)" />
                      <YAxis stroke="rgba(255,255,255,0.45)" />
                      <Tooltip content={<CarbonTooltip />} />
                      <Legend />
                      <Line
                        type="monotone"
                        dataKey="baseline"
                        name="Baseline CO₂"
                        stroke="rgba(255,255,255,0.35)"
                        strokeWidth={2}
                        dot={{ r: 3 }}
                      />
                      <Line
                        type="monotone"
                        dataKey="actual"
                        name="Actual CO₂"
                        stroke="#22c55e"
                        strokeWidth={2}
                        dot={{ r: 3 }}
                      />
                      <Line
                        type="monotone"
                        dataKey="carbon_saved"
                        name="Carbon Saved"
                        stroke="#3b82f6"
                        strokeWidth={2}
                        dot={{ r: 3 }}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                )}
              </ChartCard>

              <ChartCard title="Energy & Processing Trends" delay={0.25}>
                {sparse ? (
                  <div className="space-y-4">
                    <p className="text-sm text-muted-foreground">{emptyMessage}</p>
                    {stats.energy_trend.length > 0 ? (
                      <ResponsiveContainer width="100%" height={260}>
                        <BarChart data={stats.energy_trend}>
                          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
                          <XAxis dataKey="date" stroke="rgba(255,255,255,0.45)" />
                          <YAxis stroke="rgba(255,255,255,0.45)" />
                          <Tooltip content={<EnergyTooltip />} />
                          <Legend />
                          <Bar
                            dataKey="estimated_co2e"
                            name="Estimated CO₂"
                            fill="#22c55e"
                            radius={6}
                          />
                          <Bar
                            dataKey="docs_processed"
                            name="Documents"
                            fill="#64748b"
                            radius={6}
                          />
                        </BarChart>
                      </ResponsiveContainer>
                    ) : (
                      <div className="h-[260px] flex items-center justify-center text-sm text-muted-foreground">
                        No documents in this range yet.
                      </div>
                    )}
                  </div>
                ) : (
                  <ResponsiveContainer width="100%" height={300}>
                    <LineChart data={stats.energy_trend}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
                      <XAxis dataKey="date" stroke="rgba(255,255,255,0.45)" />
                      <YAxis stroke="rgba(255,255,255,0.45)" />
                      <Tooltip content={<EnergyTooltip />} />
                      <Legend />
                      <Line
                        type="monotone"
                        dataKey="energy_consumed_kwh"
                        name="Energy (kWh)"
                        stroke="#f59e0b"
                        strokeWidth={2}
                        dot={{ r: 3 }}
                      />
                      <Line
                        type="monotone"
                        dataKey="estimated_co2e"
                        name="Estimated CO₂"
                        stroke="#22c55e"
                        strokeWidth={2}
                        dot={{ r: 3 }}
                      />
                      <Line
                        type="monotone"
                        dataKey="docs_processed"
                        name="Documents"
                        stroke="#64748b"
                        strokeWidth={2}
                        dot={{ r: 3 }}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                )}
              </ChartCard>
            </div>

            <div className="mb-8">
              <DocumentHistory />
            </div>
          </motion.div>
        </main>
      </div>
    </div>
  )
}
