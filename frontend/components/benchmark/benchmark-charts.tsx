"use client"

import { useState } from "react"
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Rectangle,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { ChartCard } from "@/components/chart-card"
import type { DashboardPayload } from "@/lib/benchmark-types"
import { displayParticipantName, fmtNum, fmtUsd } from "@/lib/benchmark-campaigns"
import {
  CHART_AMBER,
  CHART_AXIS_TICK,
  CHART_CORAL,
  CHART_EMERALD,
  CHART_GRID,
  CHART_LEGEND_STYLE,
  CHART_TEAL,
  CHART_TICK,
  CHART_TOOLTIP_BOX,
} from "@/lib/benchmark-chart-theme"

const TEAL = CHART_TEAL
const AMBER = CHART_AMBER
const CORAL = CHART_CORAL
const EMERALD = CHART_EMERALD
const MODEL_COLORS = [TEAL, AMBER, CORAL, EMERALD, "#a78bfa", "#38bdf8", "#f472b6", "#fbbf24"]

type ScatterPoint = {
  model: string
  quality: number
  x: number
  fill: string
}

function colorByModel(models: string[]): Map<string, string> {
  const unique: string[] = []
  for (const m of models) {
    if (m && !unique.includes(m)) unique.push(m)
  }
  const map = new Map<string, string>()
  unique.forEach((m, i) => map.set(m, MODEL_COLORS[i % MODEL_COLORS.length]))
  return map
}

function ScatterTip({
  active,
  payload,
  xLabel,
  formatX,
}: {
  active?: boolean
  payload?: Array<{ payload?: ScatterPoint }>
  xLabel: string
  formatX: (v: number) => string
}) {
  if (!active || !payload?.length) return null
  const row = payload[0]?.payload
  if (!row) return null
  return (
    <div className={CHART_TOOLTIP_BOX}>
      <p className="mb-1.5 font-semibold text-white">{row.model}</p>
      <p className="text-neutral-300">Quality: {fmtNum(row.quality, 1)}</p>
      <p className="text-neutral-300">
        {xLabel}: {formatX(row.x)}
      </p>
    </div>
  )
}

function ModelScatterChart({
  points,
  xLabel,
  xUnit,
  formatX,
  accent,
}: {
  points: ScatterPoint[]
  xLabel: string
  xUnit?: string
  formatX: (v: number) => string
  accent: string
}) {
  const legend = Array.from(
    new Map(points.map((p) => [p.model, p.fill])).entries(),
  ).map(([model, fill]) => ({ model, fill }))

  return (
    <>
      <div className="h-72">
        <ResponsiveContainer width="100%" height={288} minWidth={0}>
          <ScatterChart margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
            <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
            <XAxis
              type="number"
              dataKey="x"
              name={xLabel}
              unit={xUnit}
              tick={AXIS}
              tickFormatter={(v) => formatX(Number(v))}
            />
            <YAxis
              type="number"
              dataKey="quality"
              name="Quality"
              domain={[0, 100]}
              tick={AXIS}
            />
            <Tooltip
              cursor={{ strokeDasharray: "3 3", stroke: accent }}
              content={(props) => (
                <ScatterTip
                  active={props.active}
                  payload={props.payload as Array<{ payload?: ScatterPoint }>}
                  xLabel={xLabel}
                  formatX={formatX}
                />
              )}
            />
            <Scatter data={points} name="Models">
              {points.map((p, i) => (
                <Cell key={`${p.model}-${i}`} fill={p.fill} fillOpacity={0.9} />
              ))}
            </Scatter>
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      {legend.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1.5 text-[12px] text-neutral-200">
          {legend.map((item) => (
            <span key={item.model} className="inline-flex items-center gap-1.5">
              <span
                className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
                style={{ background: item.fill }}
              />
              <span className="truncate max-w-[160px]" title={item.model}>
                {item.model}
              </span>
            </span>
          ))}
        </div>
      ) : null}
    </>
  )
}

function Tip({
  active,
  payload,
  label,
  rows,
}: {
  active?: boolean
  payload?: Array<{ name?: string; value?: number; color?: string; dataKey?: string }>
  label?: string
  rows: Array<{ label: string; format?: (v: number) => string; color?: string }>
}) {
  if (!active || !payload?.length) return null
  return (
    <div className={CHART_TOOLTIP_BOX}>
      <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.16em] text-neutral-300">
        {label}
      </p>
      <div className="space-y-1.5">
        {payload.map((p, i) => {
          const meta = rows[i] || rows.find((r) => r.label === p.name)
          const fmt = meta?.format || ((v: number) => fmtNum(v, 2))
          const color = p.color || meta?.color || TEAL
          return (
            <div key={p.name || i} className="flex items-center gap-2">
              <span
                className="h-2 w-2 shrink-0 rounded-sm"
                style={{ backgroundColor: color, boxShadow: `0 0 8px ${color}66` }}
              />
              <span className="text-neutral-300">{meta?.label || p.name}</span>
              <span className="ml-auto font-mono font-medium text-white">
                {fmt(Number(p.value))}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function InteractiveBar({
  dataKey,
  name,
  fill,
  stackId,
  radius = [3, 3, 0, 0] as [number, number, number, number],
}: {
  dataKey: string
  name: string
  fill: string
  stackId?: string
  radius?: [number, number, number, number]
}) {
  return (
    <Bar
      dataKey={dataKey}
      name={name}
      fill={fill}
      stackId={stackId}
      radius={radius}
      cursor="pointer"
      maxBarSize={48}
      activeBar={(props) => {
        const x = Number(props.x)
        const y = Number(props.y)
        const width = Number(props.width)
        const height = Number(props.height)
        if (![x, y, width, height].every(Number.isFinite) || height <= 0) {
          return <g />
        }
        const lift = 6
        return (
          <g style={{ pointerEvents: "none" }}>
            {/* Ground shadow — makes the lifted bar read as 3D */}
            <rect
              x={x + 3}
              y={y + 4}
              width={width}
              height={height}
              rx={3}
              fill="rgba(0,0,0,0.55)"
            />
            <Rectangle
              x={x}
              y={y - lift}
              width={width}
              height={height}
              fill={fill}
              radius={radius}
              stroke="rgba(255,255,255,0.9)"
              strokeWidth={1.5}
              style={{
                filter: [
                  `drop-shadow(0 12px 16px ${fill}77)`,
                  "drop-shadow(0 4px 6px rgba(0,0,0,0.55))",
                ].join(" "),
              }}
            />
          </g>
        )
      }}
    />
  )
}

const AXIS = { ...CHART_AXIS_TICK, stroke: CHART_TICK }
const GRID = CHART_GRID

type Props = { dashboard: DashboardPayload }

export default function BenchmarkCharts({ dashboard }: Props) {
  const [hiddenKeys, setHiddenKeys] = useState<Record<string, boolean>>({})

  const toggleSeries = (key: string) => {
    setHiddenKeys((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  const latency = dashboard.charts.latency_comparison.series.map((r) => ({
    model: displayParticipantName(r.model),
    avg: r.avg_latency_ms ?? 0,
    p50: r.p50_latency_ms ?? 0,
    p95: r.p95_latency_ms ?? 0,
  }))
  const ttft = dashboard.charts.ttft_comparison.series.map((r) => ({
    model: displayParticipantName(r.model),
    ttft: r.avg_ttft_ms ?? 0,
  }))
  const tokens = dashboard.charts.prompt_vs_completion_tokens.series.map((r) => ({
    model: displayParticipantName(r.model),
    prompt: r.avg_prompt_tokens ?? 0,
    completion: r.avg_completion_tokens ?? 0,
    total: (r.avg_prompt_tokens ?? 0) + (r.avg_completion_tokens ?? 0),
  }))
  const cost = dashboard.charts.estimated_cost.series.map((r) => ({
    model: displayParticipantName(r.model),
    avg: r.avg_estimated_api_cost_usd ?? 0,
    total: r.total_estimated_api_cost_usd ?? 0,
    perQ: r.avg_estimated_api_cost_usd ?? 0,
  }))
  const energy = dashboard.charts.estimated_energy.series.map((r) => ({
    model: displayParticipantName(r.model),
    energy: r.avg_estimated_energy_wh ?? 0,
  }))
  const co2 = dashboard.charts.estimated_co2e.series.map((r) => ({
    model: displayParticipantName(r.model),
    co2e: r.avg_estimated_co2e_g ?? 0,
  }))
  // Per-document totals: prefer exported totals, else avg × successful runs.
  const perDocByModel = new Map<string, { energy: number; co2e: number }>()
  for (const r of dashboard.table?.per_model || []) {
    const n = Math.max(1, Number(r.n_ok || r.n_runs || 1))
    const avgE = Number(r.avg_estimated_energy_wh || 0)
    const avgC = Number(r.avg_estimated_co2e_g || 0)
    perDocByModel.set(r.model, {
      energy: Number(
        r.total_estimated_energy_wh != null
          ? r.total_estimated_energy_wh
          : avgE * n,
      ),
      co2e: Number(
        r.total_estimated_co2e_g != null ? r.total_estimated_co2e_g : avgC * n,
      ),
    })
  }
  if (perDocByModel.size === 0) {
    for (const r of dashboard.charts.estimated_energy.series || []) {
      const cur = perDocByModel.get(r.model) || { energy: 0, co2e: 0 }
      cur.energy = Number(
        r.total_estimated_energy_wh ?? r.avg_estimated_energy_wh ?? 0,
      )
      perDocByModel.set(r.model, cur)
    }
    for (const r of dashboard.charts.estimated_co2e.series || []) {
      const cur = perDocByModel.get(r.model) || { energy: 0, co2e: 0 }
      cur.co2e = Number(r.total_estimated_co2e_g ?? r.avg_estimated_co2e_g ?? 0)
      perDocByModel.set(r.model, cur)
    }
  }
  const energyPerDoc = Array.from(perDocByModel.entries()).map(
    ([model, v]) => ({
      model: displayParticipantName(model),
      energy: v.energy,
    }),
  )
  const co2PerDoc = Array.from(perDocByModel.entries()).map(([model, v]) => ({
    model: displayParticipantName(model),
    co2e: v.co2e,
  }))
  const quality = (dashboard.charts.quality_overview?.series || []).map((r) => ({
    model: displayParticipantName(r.model),
    quality: r.avg_quality_score ?? 0,
    correctness: r.avg_correctness ?? 0,
    completeness: r.avg_completeness ?? 0,
    groundedness: r.avg_groundedness ?? 0,
    conciseness: r.avg_conciseness ?? 0,
  }))
  const qVsCostRaw = (dashboard.charts.quality_vs_cost?.points || []).map((p) => ({
    model: displayParticipantName(p.model),
    quality: Number(p.quality || 0),
    x: Number(p.cost_usd || 0),
  }))
  const qVsCo2Raw = (dashboard.charts.quality_vs_co2e?.points || []).map((p) => ({
    model: displayParticipantName(p.model),
    quality: Number(p.quality || 0),
    x: Number(p.co2e_g || 0),
  }))
  const scatterColors = colorByModel([
    ...qVsCostRaw.map((p) => p.model),
    ...qVsCo2Raw.map((p) => p.model),
  ])
  const qVsCost: ScatterPoint[] = qVsCostRaw.map((p) => ({
    ...p,
    fill: scatterColors.get(p.model) || CORAL,
  }))
  const qVsCo2: ScatterPoint[] = qVsCo2Raw.map((p) => ({
    ...p,
    fill: scatterColors.get(p.model) || TEAL,
  }))
  const dist = dashboard.charts.quality_distribution || dashboard.quality?.distribution || {}
  const insights = dashboard.quality?.insights || []

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-sm font-medium uppercase tracking-[0.14em] text-neutral-300 mb-3">
          Performance
        </h2>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <ChartCard title="Latency — avg / p50 / p95" delay={0.05}>
            <div className="h-72">
              <ResponsiveContainer width="100%" height={288} minWidth={0}>
                <BarChart data={latency} barGap={4} barCategoryGap="18%">
                  <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="model" tick={AXIS} axisLine={false} tickLine={false} />
                  <YAxis
                    tick={AXIS}
                    unit=" ms"
                    width={56}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip
                    cursor={false}
                    content={(props) => (
                      <Tip
                        {...props}
                        rows={[
                          {
                            label: "Avg",
                            color: TEAL,
                            format: (v) => `${fmtNum(v, 0)} ms`,
                          },
                          {
                            label: "p50",
                            color: AMBER,
                            format: (v) => `${fmtNum(v, 0)} ms`,
                          },
                          {
                            label: "p95",
                            color: CORAL,
                            format: (v) => `${fmtNum(v, 0)} ms`,
                          },
                        ]}
                      />
                    )}
                  />
                  <Legend
                    formatter={(value) => (
                      <span className="font-mono text-[11px] text-neutral-200">
                        {value}
                      </span>
                    )}
                    onClick={(e) => {
                      const key = String(e?.dataKey || "")
                      if (key) toggleSeries(key)
                    }}
                    wrapperStyle={CHART_LEGEND_STYLE}
                  />
                  {!hiddenKeys.avg ? (
                    <InteractiveBar dataKey="avg" name="Avg" fill={TEAL} />
                  ) : null}
                  {!hiddenKeys.p50 ? (
                    <InteractiveBar dataKey="p50" name="p50" fill={AMBER} />
                  ) : null}
                  {!hiddenKeys.p95 ? (
                    <InteractiveBar dataKey="p95" name="p95" fill={CORAL} />
                  ) : null}
                </BarChart>
              </ResponsiveContainer>
            </div>
            <p className="mt-2 font-mono text-[10px] text-neutral-400">
              Hover for values · click legend to toggle series
            </p>
          </ChartCard>

          <ChartCard title="Time to first token (TTFT)" delay={0.1}>
            <div className="h-72">
              <ResponsiveContainer width="100%" height={288} minWidth={0}>
                <BarChart data={ttft}>
                  <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="model" tick={AXIS} axisLine={false} tickLine={false} />
                  <YAxis
                    tick={AXIS}
                    unit=" ms"
                    width={56}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip
                    cursor={false}
                    content={(props) => (
                      <Tip
                        {...props}
                        rows={[
                          {
                            label: "TTFT",
                            color: TEAL,
                            format: (v) => `${fmtNum(v, 0)} ms`,
                          },
                        ]}
                      />
                    )}
                  />
                  <InteractiveBar dataKey="ttft" name="TTFT" fill={TEAL} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </ChartCard>

        </div>
      </div>

      <div>
        <h2 className="text-sm font-medium uppercase tracking-[0.14em] text-neutral-300 mb-3">
          Token usage
        </h2>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <ChartCard title="Prompt vs completion tokens" delay={0.2}>
            <div className="h-72">
              <ResponsiveContainer width="100%" height={288} minWidth={0}>
                <BarChart data={tokens}>
                  <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
                  <XAxis dataKey="model" tick={AXIS} />
                  <YAxis tick={AXIS} width={48} />
                  <Tooltip
                    cursor={false}
                    content={(props) => (
                      <Tip
                        {...props}
                        rows={[
                          { label: "Prompt", format: (v) => fmtNum(v, 0) },
                          { label: "Completion", format: (v) => fmtNum(v, 0) },
                        ]}
                      />
                    )}
                  />
                  <Legend
                    wrapperStyle={CHART_LEGEND_STYLE}
                    formatter={(value) => (
                      <span className="font-mono text-[11px] text-neutral-200">
                        {value}
                      </span>
                    )}
                  />
                  <InteractiveBar
                    dataKey="prompt"
                    name="Prompt"
                    stackId="a"
                    fill={TEAL}
                    radius={[0, 0, 0, 0]}
                  />
                  <InteractiveBar
                    dataKey="completion"
                    name="Completion"
                    stackId="a"
                    fill={AMBER}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </ChartCard>

          <ChartCard title="Total tokens (avg)" delay={0.25}>
            <div className="h-72">
              <ResponsiveContainer width="100%" height={288} minWidth={0}>
                <BarChart data={tokens}>
                  <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="model" tick={AXIS} axisLine={false} tickLine={false} />
                  <YAxis tick={AXIS} width={48} axisLine={false} tickLine={false} />
                  <Tooltip
                    cursor={false}
                    content={(props) => (
                      <Tip
                        {...props}
                        rows={[
                          {
                            label: "Total",
                            color: CORAL,
                            format: (v) => fmtNum(v, 0),
                          },
                        ]}
                      />
                    )}
                  />
                  <InteractiveBar dataKey="total" name="Total" fill={CORAL} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </ChartCard>
        </div>
      </div>

      <div>
        <h2 className="text-sm font-medium uppercase tracking-[0.14em] text-neutral-300 mb-3">
          Cost
        </h2>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <ChartCard title="Cost per question (avg)" delay={0.3}>
            <div className="h-72">
              <ResponsiveContainer width="100%" height={288} minWidth={0}>
                <BarChart data={cost}>
                  <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
                  <XAxis dataKey="model" tick={AXIS} />
                  <YAxis tick={AXIS} width={56} />
                  <Tooltip
                    cursor={false}
                    content={(props) => (
                      <Tip
                        {...props}
                        rows={[{ label: "Avg", format: (v) => fmtUsd(v, 5) }]}
                      />
                    )}
                  />
                  <InteractiveBar dataKey="perQ" name="Avg $" fill={AMBER} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </ChartCard>

          <ChartCard title="Total campaign cost" delay={0.35}>
            <div className="h-72">
              <ResponsiveContainer width="100%" height={288} minWidth={0}>
                <BarChart data={cost}>
                  <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="model" tick={AXIS} axisLine={false} tickLine={false} />
                  <YAxis tick={AXIS} width={56} axisLine={false} tickLine={false} />
                  <Tooltip
                    cursor={false}
                    content={(props) => (
                      <Tip
                        {...props}
                        rows={[
                          {
                            label: "Total",
                            color: CORAL,
                            format: (v) => fmtUsd(v, 5),
                          },
                        ]}
                      />
                    )}
                  />
                  <InteractiveBar dataKey="total" name="Total $" fill={CORAL} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </ChartCard>
        </div>
      </div>

      <div>
        <h2 className="text-sm font-medium uppercase tracking-[0.14em] text-neutral-300 mb-3">
          Sustainability
        </h2>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <ChartCard title="Estimated energy (Wh / query)" delay={0.4}>
            <div className="h-72">
              <ResponsiveContainer width="100%" height={288} minWidth={0}>
                <BarChart data={energy}>
                  <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
                  <XAxis dataKey="model" tick={AXIS} />
                  <YAxis tick={AXIS} width={48} />
                  <Tooltip
                    cursor={false}
                    content={(props) => (
                      <Tip
                        {...props}
                        rows={[
                          { label: "Energy", format: (v) => `${fmtNum(v, 3)} Wh` },
                        ]}
                      />
                    )}
                  />
                  <InteractiveBar dataKey="energy" name="Wh" fill={AMBER} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </ChartCard>

          <ChartCard title="Estimated CO₂e (g / query)" delay={0.45}>
            <div className="h-72">
              <ResponsiveContainer width="100%" height={288} minWidth={0}>
                <BarChart data={co2}>
                  <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="model" tick={AXIS} axisLine={false} tickLine={false} />
                  <YAxis tick={AXIS} width={48} axisLine={false} tickLine={false} />
                  <Tooltip
                    cursor={false}
                    content={(props) => (
                      <Tip
                        {...props}
                        rows={[
                          {
                            label: "CO₂e",
                            color: TEAL,
                            format: (v) => `${fmtNum(v, 3)} g`,
                          },
                        ]}
                      />
                    )}
                  />
                  <InteractiveBar dataKey="co2e" name="gCO₂e" fill={TEAL} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </ChartCard>

          <ChartCard title="Estimated Energy (Wh / document)" delay={0.5}>
            <div className="h-72">
              <ResponsiveContainer width="100%" height={288} minWidth={0}>
                <BarChart data={energyPerDoc}>
                  <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="model" tick={AXIS} axisLine={false} tickLine={false} />
                  <YAxis tick={AXIS} width={48} axisLine={false} tickLine={false} />
                  <Tooltip
                    cursor={false}
                    content={(props) => (
                      <Tip
                        {...props}
                        rows={[
                          {
                            label: "Energy",
                            format: (v) => `${fmtNum(v, 3)} Wh`,
                          },
                        ]}
                      />
                    )}
                  />
                  <InteractiveBar dataKey="energy" name="Wh" fill={AMBER} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </ChartCard>

          <ChartCard title="Estimated CO₂e (g / document)" delay={0.55}>
            <div className="h-72">
              <ResponsiveContainer width="100%" height={288} minWidth={0}>
                <BarChart data={co2PerDoc}>
                  <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="model" tick={AXIS} axisLine={false} tickLine={false} />
                  <YAxis tick={AXIS} width={48} axisLine={false} tickLine={false} />
                  <Tooltip
                    cursor={false}
                    content={(props) => (
                      <Tip
                        {...props}
                        rows={[
                          {
                            label: "CO₂e",
                            color: TEAL,
                            format: (v) => `${fmtNum(v, 3)} g`,
                          },
                        ]}
                      />
                    )}
                  />
                  <InteractiveBar dataKey="co2e" name="gCO₂e" fill={TEAL} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </ChartCard>
        </div>
      </div>

      {(quality.length > 0 || insights.length > 0) && (
        <div>
          <h2 className="text-sm font-medium uppercase tracking-[0.14em] text-neutral-300 mb-3">
            Quality overview
          </h2>
          {insights.length ? (
            <div className="mb-4 rounded-lg border border-border/50 bg-black/20 px-4 py-3 space-y-1.5">
              {insights.map((line) => (
                <p key={line} className="text-sm text-neutral-300 leading-relaxed">
                  {line}
                </p>
              ))}
            </div>
          ) : null}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <ChartCard title="Average quality (0–100)" delay={0.5}>
              <div className="h-72">
                <ResponsiveContainer width="100%" height={288} minWidth={0}>
                  <BarChart data={quality}>
                    <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
                    <XAxis dataKey="model" tick={AXIS} />
                    <YAxis tick={AXIS} domain={[0, 100]} width={40} />
                    <Tooltip
                      cursor={false}
                      content={(props) => (
                        <Tip
                          {...props}
                          rows={[{ label: "Quality", format: (v) => fmtNum(v, 1) }]}
                        />
                      )}
                    />
                    <InteractiveBar dataKey="quality" name="Quality" fill={TEAL} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              {dist && (dist.p50 != null || dist.min != null) ? (
                <p className="mt-2 text-[11px] text-neutral-300 font-mono">
                  distribution min {fmtNum(Number(dist.min), 1)} · p25{" "}
                  {fmtNum(Number(dist.p25), 1)} · p50 {fmtNum(Number(dist.p50), 1)} · p75{" "}
                  {fmtNum(Number(dist.p75), 1)} · max {fmtNum(Number(dist.max), 1)}
                </p>
              ) : null}
            </ChartCard>

            <ChartCard title="Quality dimensions" delay={0.55}>
              <div className="h-72">
                <ResponsiveContainer width="100%" height={288} minWidth={0}>
                  <BarChart data={quality} barGap={2}>
                    <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="model" tick={AXIS} axisLine={false} tickLine={false} />
                    <YAxis
                      tick={AXIS}
                      domain={[0, 100]}
                      width={40}
                      axisLine={false}
                      tickLine={false}
                    />
                    <Legend
                      wrapperStyle={CHART_LEGEND_STYLE}
                      formatter={(value) => (
                        <span className="font-mono text-[11px] text-neutral-200">
                          {value}
                        </span>
                      )}
                    />
                    <Tooltip
                      cursor={false}
                      content={(props) => (
                        <Tip
                          {...props}
                          rows={[
                            { label: "Correctness", color: TEAL },
                            { label: "Completeness", color: AMBER },
                            { label: "Groundedness", color: CORAL },
                            { label: "Conciseness", color: EMERALD },
                          ]}
                        />
                      )}
                    />
                    <InteractiveBar
                      dataKey="correctness"
                      name="Correctness"
                      fill={TEAL}
                      radius={[2, 2, 0, 0]}
                    />
                    <InteractiveBar
                      dataKey="completeness"
                      name="Completeness"
                      fill={AMBER}
                      radius={[2, 2, 0, 0]}
                    />
                    <InteractiveBar
                      dataKey="groundedness"
                      name="Groundedness"
                      fill={CORAL}
                      radius={[2, 2, 0, 0]}
                    />
                    <InteractiveBar
                      dataKey="conciseness"
                      name="Conciseness"
                      fill={EMERALD}
                      radius={[2, 2, 0, 0]}
                    />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </ChartCard>

            <ChartCard title="Quality vs cost" delay={0.65}>
              <ModelScatterChart
                points={qVsCost}
                xLabel="Cost"
                formatX={(v) => fmtUsd(v, 4)}
                accent={AMBER}
              />
            </ChartCard>

            <ChartCard title="Quality vs estimated CO₂e" delay={0.7}>
              <ModelScatterChart
                points={qVsCo2}
                xLabel="CO₂e"
                formatX={(v) => `${fmtNum(v, 3)} g`}
                accent={TEAL}
              />
            </ChartCard>
          </div>
        </div>
      )}
    </div>
  )
}
