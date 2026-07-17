"use client"

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { ChartCard } from "@/components/chart-card"
import type { CampaignBundle } from "@/lib/benchmark-types"
import {
  displayParticipantName,
  fmtNum,
  fmtUsd,
  modelTotalCo2eG,
  totalEstimatedCo2eG,
  totalEstimatedCostUsd,
} from "@/lib/benchmark-campaigns"
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
const RAG_COLOR = CHART_TEAL
const SUM_COLOR = CHART_AMBER
const TOTAL_COLOR = CHART_CORAL

type Point = {
  key: string
  model: string
  shortLabel: string
  workload: "RAG" | "Summarization"
  cost: number
  co2e: number
  /** Plot coordinates (may be lightly jittered for overlaps). */
  plotCost: number
  plotCo2e: number
  fill: string
  isTotal: boolean
  labelDx: number
  labelDy: number
}

function Tip({
  active,
  payload,
}: {
  active?: boolean
  payload?: Array<{ payload?: Point }>
}) {
  if (!active || !payload?.length) return null
  // Prefer the hovered point that actually has our Point payload.
  const p =
    payload.find((entry) => entry.payload?.key)?.payload ||
    payload[0]?.payload
  if (!p) return null
  return (
    <div className={CHART_TOOLTIP_BOX}>
      <p className="mb-1.5 font-semibold text-white">
        {p.isTotal ? `${p.workload} — campaign total` : p.model}
      </p>
      {!p.isTotal ? (
        <p className="text-neutral-300">
          Workload:{" "}
          <span style={{ color: p.workload === "RAG" ? RAG_COLOR : SUM_COLOR }}>
            {p.workload}
          </span>
        </p>
      ) : null}
      <p className="text-neutral-300">Cost: {fmtUsd(p.cost, 4)}</p>
      <p className="text-neutral-300">CO₂e: {fmtNum(p.co2e, 3)} g</p>
    </div>
  )
}

function shortModelLabel(model: string, isTotal: boolean, workload: string): string {
  if (isTotal) return workload === "RAG" ? "RAG Σ" : "Sum Σ"
  const m = model.trim()
  if (/intelligent\s*router/i.test(m)) return "Router"
  if (/nano/i.test(m)) return "nano"
  if (/mini/i.test(m)) return "mini"
  if (/5\.5|gpt-5\.5/i.test(m)) return "5.5"
  return m.length > 8 ? `${m.slice(0, 7)}…` : m
}

/**
 * Separate near-identical points so markers/labels do not stack.
 * Applies a small relative offset in value-space (works with log axes).
 */
function separateOverlaps(points: Point[]): Point[] {
  const out = points.map((p) => ({ ...p }))
  const n = out.length
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const a = out[i]
      const b = out[j]
      const costRatio =
        Math.max(a.plotCost, b.plotCost) / Math.max(Math.min(a.plotCost, b.plotCost), 1e-9)
      const co2Ratio =
        Math.max(a.plotCo2e, b.plotCo2e) / Math.max(Math.min(a.plotCo2e, b.plotCo2e), 1e-9)
      // Treat as overlapping when within ~12% on both log-ish axes.
      if (costRatio < 1.12 && co2Ratio < 1.12) {
        const bump = 1.08 + ((j + i) % 3) * 0.03
        // Push the later point up/right; nudge earlier one down/left slightly.
        b.plotCost *= bump
        b.plotCo2e *= bump
        a.plotCost /= Math.sqrt(bump)
        a.plotCo2e /= Math.sqrt(bump)
        a.labelDx = -10
        a.labelDy = -10
        b.labelDx = 10
        b.labelDy = 12
      }
    }
  }
  return out
}

/** Circle/square for models, diamond for campaign totals — with short labels. */
function PointShape(props: {
  cx?: number
  cy?: number
  payload?: Point
}) {
  const { cx = 0, cy = 0, payload } = props
  if (!payload) return null

  const label = payload.shortLabel
  const lx = cx + (payload.labelDx || 8)
  const ly = cy + (payload.labelDy || -8)

  if (payload.isTotal) {
    const s = 8
    return (
      <g>
        <polygon
          points={`${cx},${cy - s} ${cx + s},${cy} ${cx},${cy + s} ${cx - s},${cy}`}
          fill={TOTAL_COLOR}
          fillOpacity={0.95}
          stroke="#fff"
          strokeWidth={1.75}
        />
        <text
          x={lx}
          y={ly}
          fill="#fda4af"
          fontSize={10}
          fontWeight={600}
          style={{ paintOrder: "stroke", stroke: "rgba(0,0,0,0.75)", strokeWidth: 3 }}
        >
          {label}
        </text>
      </g>
    )
  }

  // Distinct shapes per workload so overlaps remain readable.
  if (payload.workload === "Summarization") {
    const half = 5.5
    return (
      <g>
        <rect
          x={cx - half}
          y={cy - half}
          width={half * 2}
          height={half * 2}
          rx={1.5}
          fill={payload.fill}
          fillOpacity={0.82}
          stroke="#fff"
          strokeWidth={1.25}
        />
        <text
          x={lx}
          y={ly}
          fill="#fcd34d"
          fontSize={10}
          fontWeight={600}
          style={{ paintOrder: "stroke", stroke: "rgba(0,0,0,0.75)", strokeWidth: 3 }}
        >
          {label}
        </text>
      </g>
    )
  }

  return (
    <g>
      <circle
        cx={cx}
        cy={cy}
        r={6}
        fill={payload.fill}
        fillOpacity={0.82}
        stroke="#fff"
        strokeWidth={1.25}
      />
      <text
        x={lx}
        y={ly}
        fill="#5eead4"
        fontSize={10}
        fontWeight={600}
        style={{ paintOrder: "stroke", stroke: "rgba(0,0,0,0.75)", strokeWidth: 3 }}
      >
        {label}
      </text>
    </g>
  )
}

function LegendDot({ color, diamond }: { color: string; diamond?: boolean }) {
  if (diamond) {
    return (
      <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden>
        <polygon points="6,1 11,6 6,11 1,6" fill={color} stroke="#fff" strokeWidth="1" />
      </svg>
    )
  }
  return (
    <span
      className="inline-block h-2.5 w-2.5 rounded-full"
      style={{ backgroundColor: color }}
    />
  )
}

type Props = {
  rag: CampaignBundle | null
  summarization: CampaignBundle | null
}

export function BenchmarkWorkloadCostCo2({ rag, summarization }: Props) {
  if (!rag && !summarization) return null

  const points: Point[] = []
  const ragByModel = new Map<
    string,
    { cost: number; co2e: number; label: string }
  >()
  const sumByModel = new Map<
    string,
    { cost: number; co2e: number; label: string }
  >()

  const pushPoint = (
    partial: Omit<Point, "shortLabel" | "plotCost" | "plotCo2e" | "labelDx" | "labelDy">,
  ) => {
    const cost = Math.max(partial.cost, 1e-6)
    const co2e = Math.max(partial.co2e, 1e-6)
    points.push({
      ...partial,
      cost,
      co2e,
      plotCost: cost,
      plotCo2e: co2e,
      shortLabel: shortModelLabel(partial.model, partial.isTotal, partial.workload),
      labelDx: partial.workload === "RAG" ? 8 : -28,
      labelDy: partial.isTotal ? -12 : partial.workload === "RAG" ? -9 : 14,
    })
  }

  if (rag) {
    const cost = totalEstimatedCostUsd(rag)
    const co2e = totalEstimatedCo2eG(rag)
    for (const r of rag.dashboard.table?.per_model || []) {
      const label = displayParticipantName(r.model)
      const modelCost = Number(r.total_estimated_api_cost_usd || 0)
      const modelCo2e = modelTotalCo2eG(r)
      ragByModel.set(r.model, { label, cost: modelCost, co2e: modelCo2e })
      pushPoint({
        key: `rag-${r.model}`,
        model: label,
        workload: "RAG",
        cost: modelCost,
        co2e: modelCo2e,
        fill: RAG_COLOR,
        isTotal: false,
      })
    }
    pushPoint({
      key: "rag-total",
      model: "RAG — campaign total",
      workload: "RAG",
      cost,
      co2e,
      fill: TOTAL_COLOR,
      isTotal: true,
    })
  }

  if (summarization) {
    const cost = totalEstimatedCostUsd(summarization)
    const co2e = totalEstimatedCo2eG(summarization)
    for (const r of summarization.dashboard.table?.per_model || []) {
      const label = displayParticipantName(r.model)
      const modelCost = Number(r.total_estimated_api_cost_usd || 0)
      const modelCo2e = modelTotalCo2eG(r)
      sumByModel.set(r.model, { label, cost: modelCost, co2e: modelCo2e })
      pushPoint({
        key: `sum-${r.model}`,
        model: label,
        workload: "Summarization",
        cost: modelCost,
        co2e: modelCo2e,
        fill: SUM_COLOR,
        isTotal: false,
      })
    }
    pushPoint({
      key: "sum-total",
      model: "Summarization — campaign total",
      workload: "Summarization",
      cost,
      co2e,
      fill: TOTAL_COLOR,
      isTotal: true,
    })
  }

  const modelIds = Array.from(
    new Set([...ragByModel.keys(), ...sumByModel.keys()]),
  )
  const perModelBars = modelIds.map((id) => {
    const ragRow = ragByModel.get(id)
    const sumRow = sumByModel.get(id)
    return {
      model: ragRow?.label || sumRow?.label || displayParticipantName(id),
      ragCost: ragRow?.cost ?? 0,
      sumCost: sumRow?.cost ?? 0,
      ragCo2e: ragRow?.co2e ?? 0,
      sumCo2e: sumRow?.co2e ?? 0,
    }
  })

  // Draw totals last; separate near-duplicates so the cheap cluster is readable.
  const plotPoints = separateOverlaps([
    ...points.filter((p) => !p.isTotal),
    ...points.filter((p) => p.isTotal),
  ])

  const ragLabel = rag?.index.label || "RAG"
  const sumLabel = summarization?.index.label || "Summarization"
  const docName =
    rag?.index.document_name ||
    summarization?.index.document_name ||
    rag?.config.filename ||
    summarization?.config.filename

  const minCost = Math.min(...plotPoints.map((p) => p.plotCost))
  const maxCost = Math.max(...plotPoints.map((p) => p.plotCost))
  const minCo2 = Math.min(...plotPoints.map((p) => p.plotCo2e))
  const maxCo2 = Math.max(...plotPoints.map((p) => p.plotCo2e))
  const xDomain: [number, number] = [minCost / 1.35, maxCost * 1.35]
  const yDomain: [number, number] = [minCo2 / 1.35, maxCo2 * 1.35]

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-sm font-medium uppercase tracking-[0.14em] text-neutral-300">
          Cost vs CO₂e — RAG &amp; Summarization
        </h2>
        <p className="mt-1 max-w-3xl text-sm leading-relaxed text-neutral-300">
          Campaign totals (red diamonds) and per-model totals on a log scale so cheap,
          low-CO₂e models stay readable. Prefer lower-left (cheaper &amp; greener).
          Comparing <span className="text-teal-300">{ragLabel}</span>
          {summarization ? (
            <>
              {" "}
              vs <span className="text-amber-300">{sumLabel}</span>
            </>
          ) : null}
          {docName ? <> on {docName}</> : null}.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <ChartCard title="Total cost vs total CO₂e (log scale)" delay={0.05}>
          <div className="h-80">
            <ResponsiveContainer width="100%" height={320} minWidth={0}>
              <ScatterChart margin={{ top: 18, right: 28, bottom: 28, left: 8 }}>
                <CartesianGrid stroke={CHART_GRID} strokeDasharray="3 3" />
                <XAxis
                  type="number"
                  dataKey="plotCost"
                  name="Cost"
                  scale="log"
                  domain={xDomain}
                  allowDataOverflow
                  tick={AXIS}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={(v) => fmtUsd(Number(v), 3)}
                />
                <YAxis
                  type="number"
                  dataKey="plotCo2e"
                  name="CO₂e"
                  scale="log"
                  domain={yDomain}
                  allowDataOverflow
                  tick={AXIS}
                  width={56}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={(v) => fmtNum(Number(v), 2)}
                />
                <Tooltip
                  cursor={{ strokeDasharray: "3 3", stroke: "rgba(255,255,255,0.35)" }}
                  shared={false}
                  content={<Tip />}
                />
                <Scatter
                  name="points"
                  data={plotPoints}
                  shape={(props) => (
                    <PointShape
                      cx={props.cx}
                      cy={props.cy}
                      payload={props.payload as Point | undefined}
                    />
                  )}
                  isAnimationActive={false}
                />
              </ScatterChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-1 flex flex-wrap items-center justify-center gap-x-5 gap-y-2 text-[11px] text-neutral-300">
            <span className="inline-flex items-center gap-1.5">
              <LegendDot color={RAG_COLOR} /> RAG (circle)
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span
                className="inline-block h-2.5 w-2.5 rounded-[2px]"
                style={{ backgroundColor: SUM_COLOR }}
              />{" "}
              Summarization (square)
            </span>
            <span className="inline-flex items-center gap-1.5">
              <LegendDot color={TOTAL_COLOR} diamond /> Campaign total
            </span>
          </div>
        </ChartCard>

        <ChartCard title="Per-model totals — cost & CO₂e" delay={0.1}>
          <div className="h-80 space-y-3">
            <div className="h-[148px]">
              <ResponsiveContainer width="100%" height={148} minWidth={0}>
                <BarChart data={perModelBars} barGap={3} barCategoryGap="18%">
                  <CartesianGrid stroke={CHART_GRID} strokeDasharray="3 3" vertical={false} />
                  <XAxis
                    dataKey="model"
                    tick={{ ...AXIS, fontSize: 10 }}
                    axisLine={false}
                    tickLine={false}
                    interval={0}
                  />
                  <YAxis
                    tick={AXIS}
                    width={52}
                    axisLine={false}
                    tickLine={false}
                    tickFormatter={(v) => fmtUsd(Number(v), 3)}
                  />
                  <Tooltip
                    cursor={false}
                    content={({ active, payload, label }) => {
                      if (!active || !payload?.length) return null
                      return (
                        <div className={CHART_TOOLTIP_BOX}>
                          <p className="mb-1.5 font-semibold text-white">{label}</p>
                          {payload.map((p) => (
                            <p key={String(p.dataKey)} className="text-neutral-300">
                              <span style={{ color: p.color }}>{p.name}: </span>
                              {fmtUsd(Number(p.value), 4)}
                            </p>
                          ))}
                        </div>
                      )
                    }}
                  />
                  <Legend
                    wrapperStyle={{ ...CHART_LEGEND_STYLE, fontSize: 11 }}
                    formatter={(value) => (
                      <span className="text-neutral-200">{value}</span>
                    )}
                  />
                  <Bar
                    dataKey="ragCost"
                    name="RAG"
                    fill={RAG_COLOR}
                    radius={[3, 3, 0, 0]}
                  />
                  <Bar
                    dataKey="sumCost"
                    name="Summarization"
                    fill={SUM_COLOR}
                    radius={[3, 3, 0, 0]}
                  />
                </BarChart>
              </ResponsiveContainer>
              <p className="text-center text-[11px] text-neutral-400 -mt-1">
                Total estimated API cost (USD)
              </p>
            </div>
            <div className="h-[148px]">
              <ResponsiveContainer width="100%" height={148} minWidth={0}>
                <BarChart data={perModelBars} barGap={3} barCategoryGap="18%">
                  <CartesianGrid stroke={CHART_GRID} strokeDasharray="3 3" vertical={false} />
                  <XAxis
                    dataKey="model"
                    tick={{ ...AXIS, fontSize: 10 }}
                    axisLine={false}
                    tickLine={false}
                    interval={0}
                  />
                  <YAxis
                    tick={AXIS}
                    width={52}
                    axisLine={false}
                    tickLine={false}
                    tickFormatter={(v) => fmtNum(Number(v), 1)}
                  />
                  <Tooltip
                    cursor={false}
                    content={({ active, payload, label }) => {
                      if (!active || !payload?.length) return null
                      return (
                        <div className={CHART_TOOLTIP_BOX}>
                          <p className="mb-1.5 font-semibold text-white">{label}</p>
                          {payload.map((p) => (
                            <p key={String(p.dataKey)} className="text-neutral-300">
                              <span style={{ color: p.color }}>{p.name}: </span>
                              {fmtNum(Number(p.value), 3)} g
                            </p>
                          ))}
                        </div>
                      )
                    }}
                  />
                  <Bar
                    dataKey="ragCo2e"
                    name="RAG"
                    fill={RAG_COLOR}
                    radius={[3, 3, 0, 0]}
                  />
                  <Bar
                    dataKey="sumCo2e"
                    name="Summarization"
                    fill={SUM_COLOR}
                    radius={[3, 3, 0, 0]}
                  />
                </BarChart>
              </ResponsiveContainer>
              <p className="text-center text-[11px] text-neutral-400 -mt-1">
                Total estimated CO₂e (g)
              </p>
            </div>
          </div>
        </ChartCard>
      </div>
    </div>
  )
}
