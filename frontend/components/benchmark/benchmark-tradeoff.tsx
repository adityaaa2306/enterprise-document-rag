"use client"

import {
  CartesianGrid,
  Cell,
  Legend,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts"
import { ChartCard } from "@/components/chart-card"
import type { DashboardPayload, ModelChartRow } from "@/lib/benchmark-types"
import { displayParticipantName, fmtNum, fmtUsd } from "@/lib/benchmark-campaigns"
import {
  CHART_AMBER,
  CHART_AXIS_TICK,
  CHART_AXIS_TICK_SM,
  CHART_CORAL,
  CHART_EMERALD,
  CHART_GRID,
  CHART_LEGEND_STYLE,
  CHART_TEAL,
  CHART_TICK,
  CHART_TOOLTIP_BOX,
} from "@/lib/benchmark-chart-theme"

const COLORS = [CHART_TEAL, CHART_AMBER, CHART_CORAL, CHART_EMERALD]

function invertNormalize(values: number[], value: number): number {
  const min = Math.min(...values)
  const max = Math.max(...values)
  if (!Number.isFinite(min) || !Number.isFinite(max) || max === min) return 50
  // Lower is better → invert so higher score = better
  return ((max - value) / (max - min)) * 100
}

function normalize(values: number[], value: number): number {
  const min = Math.min(...values)
  const max = Math.max(...values)
  if (!Number.isFinite(min) || !Number.isFinite(max) || max === min) return 50
  return ((value - min) / (max - min)) * 100
}

export function BenchmarkTradeoff({ dashboard }: { dashboard: DashboardPayload }) {
  const rows: ModelChartRow[] = dashboard.table?.per_model || []
  const latencies = rows.map((r) => Number(r.avg_latency_ms || 0))
  const costs = rows.map((r) => Number(r.total_estimated_api_cost_usd || 0))
  const co2s = rows.map((r) => Number(r.avg_estimated_co2e_g || 0))
  const tps = rows.map((r) => Number(r.avg_tokens_per_sec || 0))

  const scatter = rows.map((r, i) => ({
    model: r.model,
    short: displayParticipantName(r.model),
    latency: Number(r.avg_latency_ms || 0),
    cost: Number(r.total_estimated_api_cost_usd || 0),
    co2e: Number(r.avg_estimated_co2e_g || 0),
    fill: COLORS[i % COLORS.length],
  }))

  // Radar: higher = better (speed, cheapness, greenness, throughput)
  const radar = rows.map((r) => ({
    model: displayParticipantName(r.model),
    speed: invertNormalize(latencies, Number(r.avg_latency_ms || 0)),
    cost: invertNormalize(costs, Number(r.total_estimated_api_cost_usd || 0)),
    carbon: invertNormalize(co2s, Number(r.avg_estimated_co2e_g || 0)),
    throughput: normalize(tps, Number(r.avg_tokens_per_sec || 0)),
  }))

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-sm font-medium uppercase tracking-[0.14em] text-neutral-300">
          Decision trade-offs
        </h2>
        <p className="mt-1 max-w-3xl text-sm leading-relaxed text-neutral-300">
          Compare latency, estimated cost, and estimated CO₂e across models. Prefer points
          toward the lower-left of the scatter (faster & cheaper); bubble size scales with
          CO₂e. Radar scores are normalized so higher is better.
        </p>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <ChartCard title="Latency vs cost (bubble = CO₂e)" delay={0.05}>
          <div className="h-80">
            <ResponsiveContainer width="100%" height={320} minWidth={0}>
              <ScatterChart margin={{ top: 12, right: 16, bottom: 12, left: 8 }}>
                <CartesianGrid stroke={CHART_GRID} strokeDasharray="3 3" />
                <XAxis
                  type="number"
                  dataKey="latency"
                  name="Latency"
                  unit=" ms"
                  tick={CHART_AXIS_TICK}
                  stroke={CHART_TICK}
                  tickFormatter={(v) => `${Math.round(v)}`}
                />
                <YAxis
                  type="number"
                  dataKey="cost"
                  name="Cost"
                  unit=" $"
                  width={56}
                  tick={CHART_AXIS_TICK}
                  stroke={CHART_TICK}
                  tickFormatter={(v) => `$${Number(v).toFixed(3)}`}
                />
                <ZAxis type="number" dataKey="co2e" range={[80, 320]} name="CO₂e" />
                <Tooltip
                  cursor={{ strokeDasharray: "3 3", stroke: CHART_TEAL }}
                  content={({ active, payload }) => {
                    if (!active || !payload?.length) return null
                    const row = payload[0].payload as (typeof scatter)[0]
                    return (
                      <div className={CHART_TOOLTIP_BOX}>
                        <p className="mb-1 font-semibold text-white">{row.short}</p>
                        <p className="text-neutral-300">
                          Latency: {fmtNum(row.latency, 0)} ms
                        </p>
                        <p className="text-neutral-300">Cost: {fmtUsd(row.cost, 5)}</p>
                        <p className="text-neutral-300">
                          CO₂e: {fmtNum(row.co2e, 3)} g/query
                        </p>
                      </div>
                    )
                  }}
                />
                <Scatter data={scatter} name="Models">
                  {scatter.map((s) => (
                    <Cell key={s.model} fill={s.fill} />
                  ))}
                </Scatter>
              </ScatterChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-2 flex flex-wrap gap-3 text-[12px] text-neutral-200">
            {scatter.map((s) => (
              <span key={s.model} className="inline-flex items-center gap-1.5">
                <span
                  className="inline-block h-2.5 w-2.5 rounded-full"
                  style={{ background: s.fill }}
                />
                {s.short}
              </span>
            ))}
          </div>
        </ChartCard>

        <ChartCard title="Normalized preference radar (higher = better)" delay={0.1}>
          <div className="h-80">
            <ResponsiveContainer width="100%" height={320} minWidth={0}>
              <RadarChart data={radar}>
                <PolarGrid stroke={CHART_GRID} />
                <PolarAngleAxis
                  dataKey="model"
                  tick={CHART_AXIS_TICK}
                  stroke={CHART_TICK}
                />
                <PolarRadiusAxis
                  angle={30}
                  domain={[0, 100]}
                  tick={CHART_AXIS_TICK_SM}
                  stroke={CHART_TICK}
                />
                <Radar
                  name="Speed"
                  dataKey="speed"
                  stroke={CHART_TEAL}
                  fill={CHART_TEAL}
                  fillOpacity={0.15}
                />
                <Radar
                  name="Cost efficiency"
                  dataKey="cost"
                  stroke={CHART_AMBER}
                  fill={CHART_AMBER}
                  fillOpacity={0.12}
                />
                <Radar
                  name="Carbon efficiency"
                  dataKey="carbon"
                  stroke={CHART_CORAL}
                  fill={CHART_CORAL}
                  fillOpacity={0.18}
                />
                <Legend wrapperStyle={CHART_LEGEND_STYLE} />
                <Tooltip
                  content={({ active, payload, label }) => {
                    if (!active || !payload?.length) return null
                    return (
                      <div className={CHART_TOOLTIP_BOX}>
                        <p className="mb-1 font-semibold text-white">{label}</p>
                        {payload.map((p) => (
                          <p key={String(p.name)} className="text-neutral-300">
                            {p.name}: {fmtNum(Number(p.value), 0)}
                          </p>
                        ))}
                      </div>
                    )
                  }}
                />
              </RadarChart>
            </ResponsiveContainer>
          </div>
        </ChartCard>
      </div>
    </div>
  )
}
