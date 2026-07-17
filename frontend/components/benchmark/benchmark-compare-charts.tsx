"use client"

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { ChartCard } from "@/components/chart-card"
import type { CampaignBundle } from "@/lib/benchmark-types"
import { modelMetric, unionModels } from "@/lib/benchmark-compare"
import { displayParticipantName, fmtNum, fmtUsd } from "@/lib/benchmark-campaigns"
import {
  CHART_AMBER,
  CHART_AXIS_TICK,
  CHART_GRID,
  CHART_LEGEND_STYLE,
  CHART_TEAL,
  CHART_TICK,
  CHART_TOOLTIP_BOX,
} from "@/lib/benchmark-chart-theme"

const AXIS = { ...CHART_AXIS_TICK, stroke: CHART_TICK }
const GRID = CHART_GRID
const A = CHART_AMBER
const B = CHART_TEAL

function Tip({
  active,
  payload,
  label,
  format,
}: {
  active?: boolean
  payload?: Array<{ name?: string; value?: number; color?: string }>
  label?: string
  format: (v: number) => string
}) {
  if (!active || !payload?.length) return null
  return (
    <div className={CHART_TOOLTIP_BOX}>
      <p className="mb-1.5 font-semibold text-white">{label}</p>
      {payload.map((p, i) => (
        <p key={p.name || i} className="text-neutral-300">
          <span style={{ color: p.color }}>{p.name}: </span>
          {format(Number(p.value))}
        </p>
      ))}
    </div>
  )
}

function DualBar({
  title,
  data,
  format,
  unit,
  delay,
}: {
  title: string
  data: Array<{ model: string; baseline: number; comparison: number }>
  format: (v: number) => string
  unit?: string
  delay: number
}) {
  const max = Math.max(
    ...data.flatMap((d) => [d.baseline, d.comparison]),
    0.0001,
  )
  return (
    <ChartCard title={title} delay={delay}>
      <div className="h-72">
        <ResponsiveContainer width="100%" height={288} minWidth={0}>
          <BarChart data={data} barGap={4}>
            <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
            <XAxis dataKey="model" tick={AXIS} />
            <YAxis
              tick={AXIS}
              unit={unit}
              width={56}
              domain={[0, max * 1.1]}
              tickFormatter={(v) =>
                unit === " $"
                  ? Number(v).toFixed(3)
                  : String(Math.round(Number(v)))
              }
            />
            <Tooltip
              content={(props) => <Tip {...props} format={format} />}
            />
            <Legend
              wrapperStyle={CHART_LEGEND_STYLE}
              formatter={(value) => (
                <span className="text-[11px] text-neutral-200">{value}</span>
              )}
            />
            <Bar
              dataKey="baseline"
              name="Campaign A"
              fill={A}
              radius={[3, 3, 0, 0]}
            />
            <Bar
              dataKey="comparison"
              name="Campaign B"
              fill={B}
              radius={[3, 3, 0, 0]}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  )
}

export default function BenchmarkCompareCharts({
  baseline,
  comparison,
  labelA,
  labelB,
}: {
  baseline: CampaignBundle
  comparison: CampaignBundle
  labelA: string
  labelB: string
}) {
  const models = unionModels(baseline, comparison)
  const short = (m: string) => displayParticipantName(m)

  const latency = models.map((m) => ({
    model: short(m),
    baseline: modelMetric(baseline, m, "avg_latency_ms") || 0,
    comparison: modelMetric(comparison, m, "avg_latency_ms") || 0,
  }))
  const cost = models.map((m) => ({
    model: short(m),
    baseline: modelMetric(baseline, m, "total_estimated_api_cost_usd") || 0,
    comparison: modelMetric(comparison, m, "total_estimated_api_cost_usd") || 0,
  }))
  const energy = models.map((m) => ({
    model: short(m),
    baseline: modelMetric(baseline, m, "avg_estimated_energy_wh") || 0,
    comparison: modelMetric(comparison, m, "avg_estimated_energy_wh") || 0,
  }))
  const co2e = models.map((m) => ({
    model: short(m),
    baseline: modelMetric(baseline, m, "avg_estimated_co2e_g") || 0,
    comparison: modelMetric(comparison, m, "avg_estimated_co2e_g") || 0,
  }))
  void labelA
  void labelB

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-sm font-medium uppercase tracking-[0.14em] text-neutral-300">
          Side-by-side charts
        </h2>
        <p className="mt-1 text-sm text-neutral-300">
          Campaign A (baseline) vs Campaign B (comparison). Paired charts share a common
          Y-axis scale per metric.
        </p>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <DualBar
          title="Latency"
          data={latency}
          unit=" ms"
          format={(v) => `${fmtNum(v, 0)} ms`}
          delay={0.04}
        />
        <DualBar
          title="Estimated cost"
          data={cost}
          unit=" $"
          format={(v) => fmtUsd(v, 5)}
          delay={0.08}
        />
        <DualBar
          title="Estimated energy"
          data={energy}
          unit=" Wh"
          format={(v) => `${fmtNum(v, 3)} Wh`}
          delay={0.12}
        />
        <DualBar
          title="Estimated CO₂e"
          data={co2e}
          unit=" g"
          format={(v) => `${fmtNum(v, 3)} g`}
          delay={0.16}
        />
      </div>
    </div>
  )
}
