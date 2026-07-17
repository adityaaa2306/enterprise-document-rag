"use client"

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { ChartCard } from "@/components/chart-card"
import type { CampaignBundle, CampaignIndexEntry } from "@/lib/benchmark-types"
import { timelinePoints } from "@/lib/benchmark-compare"
import { fmtDate, fmtNum, fmtUsd } from "@/lib/benchmark-campaigns"
import {
  CHART_AMBER,
  CHART_AXIS_TICK,
  CHART_CORAL,
  CHART_GRID,
  CHART_LEGEND_STYLE,
  CHART_TEAL,
  CHART_TICK,
  CHART_TOOLTIP_BOX,
} from "@/lib/benchmark-chart-theme"

const AXIS = { ...CHART_AXIS_TICK, stroke: CHART_TICK }
const GRID = CHART_GRID

export function BenchmarkCompareTimeline({
  campaigns,
  bundles,
}: {
  campaigns: CampaignIndexEntry[]
  bundles: Record<string, CampaignBundle | undefined>
}) {
  const points = timelinePoints(campaigns, bundles).map((p) => ({
    ...p,
    tick: `v${p.version}`,
    labelShort: (p.label || "").replace(/\s*\(failed.*\)$/i, "") || p.tick,
  }))

  if (points.length < 2) {
    return (
      <ChartCard title="Trend timeline" delay={0.05}>
        <p className="py-8 text-center text-sm text-neutral-300">
          Need at least two campaigns in history to plot a timeline.
        </p>
      </ChartCard>
    )
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-sm font-medium uppercase tracking-[0.14em] text-neutral-300">
          Trend timeline
        </h2>
        <p className="mt-1 text-sm text-neutral-300">
          Performance history across stored campaigns — latency, cost, CO₂e, and
          throughput.
        </p>
      </div>

      <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-neutral-300">
        {points.map((p, i) => (
          <span key={p.campaign_id} className="inline-flex items-center gap-2">
            <span className="rounded border border-white/15 bg-black/25 px-2 py-1 font-mono text-neutral-200">
              {p.tick}
            </span>
            {i < points.length - 1 ? <span className="text-neutral-500">↓</span> : null}
          </span>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <ChartCard title="Latency over campaigns" delay={0.04}>
          <div className="h-64">
            <ResponsiveContainer width="100%" height={256} minWidth={0}>
              <LineChart data={points}>
                <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
                <XAxis dataKey="tick" tick={AXIS} />
                <YAxis tick={AXIS} unit=" ms" width={56} />
                <Tooltip
                  content={({ active, payload }) => {
                    if (!active || !payload?.length) return null
                    const row = payload[0].payload as (typeof points)[0]
                    return (
                      <div className={CHART_TOOLTIP_BOX}>
                        <p className="font-semibold text-white">{row.label}</p>
                        <p className="text-neutral-300">{fmtDate(row.timestamp_utc)}</p>
                        <p className="mt-1 text-neutral-200">
                          Latency: {fmtNum(row.latency, 0)} ms
                        </p>
                      </div>
                    )
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="latency"
                  name="Avg latency"
                  stroke={CHART_TEAL}
                  strokeWidth={2}
                  dot={{ r: 4, fill: CHART_TEAL }}
                  connectNulls={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </ChartCard>

        <ChartCard title="Cost over campaigns" delay={0.08}>
          <div className="h-64">
            <ResponsiveContainer width="100%" height={256} minWidth={0}>
              <LineChart data={points}>
                <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
                <XAxis dataKey="tick" tick={AXIS} />
                <YAxis
                  tick={AXIS}
                  width={56}
                  tickFormatter={(v) => `$${Number(v).toFixed(2)}`}
                />
                <Tooltip
                  content={({ active, payload }) => {
                    if (!active || !payload?.length) return null
                    const row = payload[0].payload as (typeof points)[0]
                    return (
                      <div className={CHART_TOOLTIP_BOX}>
                        <p className="font-semibold text-white">{row.label}</p>
                        <p className="text-neutral-200">Cost: {fmtUsd(row.cost, 5)}</p>
                      </div>
                    )
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="cost"
                  name="Total cost"
                  stroke={CHART_AMBER}
                  strokeWidth={2}
                  dot={{ r: 4, fill: CHART_AMBER }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </ChartCard>

        <ChartCard title="CO₂e over campaigns" delay={0.12}>
          <div className="h-64">
            <ResponsiveContainer width="100%" height={256} minWidth={0}>
              <LineChart data={points}>
                <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
                <XAxis dataKey="tick" tick={AXIS} />
                <YAxis tick={AXIS} unit=" g" width={48} />
                <Legend
                  wrapperStyle={CHART_LEGEND_STYLE}
                  formatter={(value) => (
                    <span className="text-[11px] text-neutral-200">{value}</span>
                  )}
                />
                <Tooltip
                  formatter={(v: number) => [`${fmtNum(v, 3)} g`, "CO₂e"]}
                />
                <Line
                  type="monotone"
                  dataKey="co2e"
                  name="Avg CO₂e"
                  stroke={CHART_CORAL}
                  strokeWidth={2}
                  dot={{ r: 4, fill: CHART_CORAL }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </ChartCard>

        <ChartCard title="Throughput over campaigns" delay={0.16}>
          <div className="h-64">
            <ResponsiveContainer width="100%" height={256} minWidth={0}>
              <LineChart data={points}>
                <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
                <XAxis dataKey="tick" tick={AXIS} />
                <YAxis tick={AXIS} width={48} />
                <Tooltip
                  formatter={(v: number) => [`${fmtNum(v, 1)} tok/s`, "Throughput"]}
                />
                <Line
                  type="monotone"
                  dataKey="throughput"
                  name="Tokens/sec"
                  stroke={CHART_TEAL}
                  strokeWidth={2}
                  dot={{ r: 4, fill: CHART_TEAL }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </ChartCard>
      </div>
    </div>
  )
}
