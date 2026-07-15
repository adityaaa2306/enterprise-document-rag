"use client"

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { ChartCard } from "@/components/chart-card"

type TrendPoint = {
  date: string
  date_iso?: string
  savings?: number
  carbon_saved?: number
  baseline?: number
  actual?: number
  efficiency?: number
  docs_processed?: number
}

type EnergyPoint = {
  date: string
  date_iso?: string
  energy_consumed_kwh?: number
  estimated_co2e?: number
  docs_processed?: number
}

type ModelBar = {
  model: string
  estimated_gco2e: number
  is_ours: boolean
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

function ModelTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null
  const row = payload[0]?.payload as ModelBar
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2 text-xs shadow-xl">
      <p className="font-semibold mb-1">{row.model}</p>
      <p>Estimated CO₂e: {fmt(row.estimated_gco2e)} g</p>
      {row.is_ours ? <p className="text-emerald-400">Our system</p> : null}
    </div>
  )
}

type Props = {
  carbonTrend: TrendPoint[]
  energyTrend: EnergyPoint[]
  modelBars?: ModelBar[]
  sparse: boolean
  emptyMessage: string
}

export default function DashboardCharts({
  carbonTrend,
  energyTrend,
  modelBars = [],
  sparse,
  emptyMessage,
}: Props) {
  const showModels = modelBars.length > 0

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
      <ChartCard title="Daily Carbon Savings vs Baseline" delay={0.2}>
        {sparse ? (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">{emptyMessage}</p>
            {carbonTrend.length > 0 ? (
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={carbonTrend}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
                  <XAxis dataKey="date" stroke="rgba(255,255,255,0.45)" />
                  <YAxis stroke="rgba(255,255,255,0.45)" />
                  <Tooltip content={<CarbonTooltip />} />
                  <Legend />
                  <Bar dataKey="baseline" name="Baseline CO₂" fill="#64748b" radius={6} />
                  <Bar dataKey="actual" name="Actual CO₂" fill="#22c55e" radius={6} />
                  <Bar dataKey="carbon_saved" name="Carbon Saved" fill="#3b82f6" radius={6} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[260px] flex items-center justify-center text-sm text-muted-foreground">
                No finalized job metrics yet.
              </div>
            )}
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={carbonTrend}>
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

      <ChartCard
        title={showModels ? "Model CO₂e (same as Results)" : "Energy & Processing Trends"}
        delay={0.25}
      >
        {showModels ? (
          <ResponsiveContainer width="100%" height={sparse ? 260 : 300}>
            <BarChart data={modelBars} layout="vertical" margin={{ left: 8, right: 12 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
              <XAxis type="number" stroke="rgba(255,255,255,0.45)" />
              <YAxis
                type="category"
                dataKey="model"
                width={110}
                stroke="rgba(255,255,255,0.45)"
                tick={{ fontSize: 11 }}
              />
              <Tooltip content={<ModelTooltip />} />
              <Bar dataKey="estimated_gco2e" name="g CO₂e" radius={4}>
                {modelBars.map((b, i) => (
                  <Cell key={`${b.model}-${i}`} fill={b.is_ours ? "#22c55e" : "#64748b"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        ) : sparse ? (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">{emptyMessage}</p>
            {energyTrend.length > 0 ? (
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={energyTrend}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
                  <XAxis dataKey="date" stroke="rgba(255,255,255,0.45)" />
                  <YAxis stroke="rgba(255,255,255,0.45)" />
                  <Tooltip content={<EnergyTooltip />} />
                  <Legend />
                  <Bar dataKey="estimated_co2e" name="Estimated CO₂" fill="#22c55e" radius={6} />
                  <Bar dataKey="docs_processed" name="Documents" fill="#64748b" radius={6} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[260px] flex items-center justify-center text-sm text-muted-foreground">
                No finalized job metrics yet.
              </div>
            )}
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={energyTrend}>
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
  )
}
