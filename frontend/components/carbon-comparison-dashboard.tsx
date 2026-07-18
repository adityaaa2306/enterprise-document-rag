"use client"

import { motion } from "framer-motion"
import {
  Bar,
  BarChart,
  Cell,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { ChartFrame } from "@/components/chart-frame"
import { Leaf, Gauge, Scale, TrendingDown, Info } from "lucide-react"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion"
import {
  Tooltip as UiTooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import {
  buildFrontierComparisonFromCarbon,
  type CarbonLike,
} from "@/lib/frontier-carbon-compare"

export interface ComparisonModelRow {
  model: string
  relative_factor?: number
  estimated_gco2e: number
  saved_gco2e: number
  reduction_percent: number
}

export interface OurSystemCarbon {
  name: string
  tagline?: string | null
  carbon: number
}

export interface CarbonSummaryCards {
  actual_emissions_gco2e: number
  carbon_saved_gco2e: number
  reduction_percent: number
  heavy_model_baseline_gco2e: number
  estimated_optimized_pipeline_emissions_g?: number
  estimated_baseline_pipeline_emissions_g?: number
  emissions_direction?: string | null
  reporting_boundary_label?: string | null
}

export interface ChunkBreakdownRow {
  chunk_index?: number
  tier?: string
  model?: string
  input_tokens?: number
  map_tokens?: number
  energy_kwh?: number
  co2e_g?: number
  j_per_token?: number
}

export interface ChartBarRow {
  model: string
  estimated_gco2e: number
  is_ours?: boolean
}

export interface StageEmissions {
  parsing_gco2e?: number
  chunking_gco2e?: number
  embedding_gco2e?: number
  retrieval_gco2e?: number
  routing_gco2e?: number
  inference_gco2e?: number
  verification_gco2e?: number
  infrastructure_gco2e?: number
  total_gco2e?: number
}

export interface RoutingImpact {
  total_chunks?: number
  light_chunks?: number
  medium_chunks?: number
  heavy_chunks?: number
  escalated_chunks?: number
  compile_calls?: number
  co2e_vs_all_heavy_map_g_saved?: number
  pipeline_co2e_g_saved_vs_baseline?: number
}

export interface UncertaintyBand {
  enabled?: boolean
  baseline?: { low_gco2e?: number; typical_gco2e?: number; high_gco2e?: number }
  optimized?: { low_gco2e?: number; typical_gco2e?: number; high_gco2e?: number }
}

export interface CarbonBreakdown {
  input_tokens?: number
  retrieved_context_tokens?: number
  generated_tokens?: number
  effective_tokens?: number
  baseline_energy_kwh?: number
  optimized_energy_kwh?: number
  grid_carbon_intensity_gco2_kwh?: number
  baseline_co2e_g?: number
  actual_co2e_g?: number
  carbon_saved_g?: number
  reduction_percent?: number
  emissions_direction?: string | null
  estimated_baseline_pipeline_emissions_g?: number
  estimated_optimized_pipeline_emissions_g?: number
  reporting_boundary_label?: string | null
  pue?: number
  grid_zone?: string | null
  grid_datetime?: string | null
  grid_updated_at?: string | null
  grid_source?: string | null
  baseline_stages_gco2e?: StageEmissions | null
  optimized_stages_gco2e?: StageEmissions | null
  routing_impact?: RoutingImpact | null
  uncertainty?: UncertaintyBand | null
  assumptions_panel?: string | null
  equation?: string | null
  baseline_definition?: string | null
  optimized_definition?: string | null
  chunk_breakdown?: ChunkBreakdownRow[] | null
}

export interface CarbonComparisonProps {
  comparisonModels?: ComparisonModelRow[] | null
  ourSystem?: OurSystemCarbon | null
  summaryCards?: CarbonSummaryCards | null
  badges?: string[] | null
  chartBars?: ChartBarRow[] | null
  methodology?: string | null
  breakdown?: CarbonBreakdown | null
  /** When set, used to rebuild bars if API still sends legacy 252g values. */
  carbonData?: CarbonLike | null
}

function fmtG(value: number | undefined | null, digits = 2) {
  if (value == null || Number.isNaN(Number(value))) return "—"
  return Number(value).toFixed(digits)
}

function shortChartLabel(name: string) {
  if (
    name.includes("EcoRoute AI") ||
    name.includes("CarbonRoute AI") ||
    name.includes("Green Agentic")
  )
    return "EcoRoute AI"
  if (name.startsWith("Claude")) return "Claude Opus"
  if (name.startsWith("Gemini")) return "Gemini 2.5"
  if (name.includes("Behemoth")) return "Llama Behemoth"
  if (name.includes("Maverick")) return "Llama Maverick"
  return name
}

const CHART_TICK = "#d4d4d8"
const CHART_AXIS = "#71717a"
const DEFAULT_METHODOLOGY =
  "Operational emissions (Boundary A): tokens × J/token × PUE × live Electricity Maps intensity. Estimates only — training and hardware manufacturing excluded."

function sanitizeMethodology(text?: string | null): string {
  const raw = (text || "").trim()
  if (!raw || /chatgpt-class|4\.32\s*g|15\s*mg|chunk count\s*×/i.test(raw)) {
    return DEFAULT_METHODOLOGY
  }
  return raw
}

export function CarbonComparisonDashboard({
  comparisonModels,
  ourSystem,
  summaryCards,
  badges,
  chartBars,
  methodology,
  breakdown,
  carbonData,
}: CarbonComparisonProps) {
  // Always prefer a rebuild from carbon_data when available so legacy
  // comparison_models (e.g. 252 g chunk×grams bars) cannot win.
  const rebuilt = carbonData
    ? buildFrontierComparisonFromCarbon(carbonData)
    : null

  const models = rebuilt?.comparison_models ?? comparisonModels
  const system = rebuilt?.our_system ?? ourSystem
  const cardsData = rebuilt?.summary_cards ?? summaryCards
  const badgeList = rebuilt?.badges ?? badges
  const bars = rebuilt?.chart_bars ?? chartBars
  const methodText = sanitizeMethodology(rebuilt?.methodology ?? methodology)

  if (!cardsData || !models?.length || !system) {
    return null
  }

  const baselineEst =
    cardsData.estimated_baseline_pipeline_emissions_g ??
    cardsData.heavy_model_baseline_gco2e
  const optimizedEst =
    cardsData.estimated_optimized_pipeline_emissions_g ??
    cardsData.actual_emissions_gco2e
  const boundaryLabel =
    cardsData.reporting_boundary_label ||
    breakdown?.reporting_boundary_label ||
    "Operational Emissions (Boundary A)"
  const savedVal = Number(cardsData.carbon_saved_gco2e)
  const reductionVal = Number(cardsData.reduction_percent)
  const increased =
    cardsData.emissions_direction === "increased" ||
    breakdown?.emissions_direction === "increased" ||
    savedVal < 0
  const chunkRows =
    rebuilt?.chunk_breakdown ||
    breakdown?.chunk_breakdown ||
    carbonData?.chunk_breakdown ||
    []

  const cards = [
    {
      title: "Estimated Optimized Pipeline",
      value: fmtG(optimizedEst),
      unit: "g CO₂e",
      icon: Leaf,
      accent: "text-green-400",
      tip: "Per-chunk Light/Medium/Heavy routing + selected compile tier (Boundary A)",
    },
    {
      title: increased ? "Increased Emissions" : "Estimated Carbon Saved",
      value: fmtG(Math.abs(savedVal)),
      unit: "g CO₂e",
      icon: TrendingDown,
      accent: increased ? "text-rose-400" : "text-emerald-400",
      tip: increased
        ? "Optimized emitted more than the naive frontier baseline (signed: baseline − optimized)"
        : "Baseline − optimized (signed; negative shown as increased emissions)",
    },
    {
      title: "Estimated Reduction",
      value: `${reductionVal > 0 ? "+" : ""}${Math.round(reductionVal)}`,
      unit: "%",
      icon: Gauge,
      accent: increased ? "text-rose-400" : "text-blue-400",
      tip: "(carbon saved / baseline) × 100 — may be negative",
    },
    {
      title: "Estimated Baseline Pipeline",
      value: fmtG(baselineEst),
      unit: "g CO₂e",
      icon: Scale,
      accent: "text-amber-400",
      tip: "Naive single-frontier (heavy) model for all map + compile — no smart routing",
    },
  ]

  const chartData = (bars && bars.length > 0
    ? bars
    : [
        ...models.map((m) => ({
          model: m.model,
          estimated_gco2e: m.estimated_gco2e,
          is_ours: false,
        })),
        {
          model: system.name,
          estimated_gco2e: system.carbon,
          is_ours: true,
        },
      ]
  ).map((row) => ({
    ...row,
    label: shortChartLabel(row.model),
  }))

  return (
    <TooltipProvider delayDuration={200}>
      <motion.section
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.45 }}
        className="space-y-6"
      >
        <div>
          <h2 className="text-2xl font-bold tracking-tight">
            Estimated Carbon Footprint Comparison
          </h2>
          <p className="text-muted-foreground mt-1">
            Estimated emissions for processing this document.
          </p>
        </div>

        {badgeList && badgeList.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {badgeList.map((badge) => (
              <Badge
                key={badge}
                variant="outline"
                className="border-green-500/40 bg-green-500/10 text-green-300 px-3 py-1"
              >
                <Leaf className="w-3.5 h-3.5 mr-1.5" />
                {badge}
              </Badge>
            ))}
          </div>
        ) : null}

        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
          {cards.map((card, idx) => {
            const Icon = card.icon
            return (
              <motion.div
                key={card.title}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.05 * idx, duration: 0.35 }}
              >
                <Card className="p-5 bg-gradient-to-br from-card to-card/50 border-border/50 hover:border-primary/30 transition-colors h-full">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-1.5 mb-2">
                        <p className="text-sm text-muted-foreground">{card.title}</p>
                        <UiTooltip>
                          <TooltipTrigger asChild>
                            <button
                              type="button"
                              className="text-muted-foreground/70 hover:text-muted-foreground"
                              aria-label={`${card.title} info`}
                            >
                              <Info className="w-3.5 h-3.5" />
                            </button>
                          </TooltipTrigger>
                          <TooltipContent className="max-w-xs">{card.tip}</TooltipContent>
                        </UiTooltip>
                      </div>
                      <div className="flex items-baseline gap-2">
                        <p className="text-3xl font-bold text-foreground">{card.value}</p>
                        <span className="text-sm text-muted-foreground">{card.unit}</span>
                      </div>
                    </div>
                    <div className="w-10 h-10 rounded-lg bg-primary/15 flex items-center justify-center shrink-0">
                      <Icon className={`w-5 h-5 ${card.accent}`} />
                    </div>
                  </div>
                </Card>
              </motion.div>
            )
          })}
        </div>

        <Card className="overflow-hidden border-border/50 bg-gradient-to-br from-card to-card/40">
          <div className="px-6 py-4 border-b border-border/40">
            <h3 className="font-semibold">Model comparison</h3>
            <p className="text-sm text-muted-foreground">
              What if the entire document workflow ran on a single model? Same
              map+compile token mass as the naive frontier baseline.
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted-foreground border-b border-border/40">
                  <th className="px-6 py-3 font-medium">Model</th>
                  <th className="px-6 py-3 font-medium">Estimated CO₂ (g)</th>
                  <th className="px-6 py-3 font-medium">Saved vs Our System</th>
                  <th className="px-6 py-3 font-medium">Reduction %</th>
                </tr>
              </thead>
              <tbody>
                {models.map((row) => {
                  const savedPositive = row.saved_gco2e > 0
                  const reductionAbs = Math.min(100, Math.abs(row.reduction_percent))
                  return (
                  <tr
                    key={row.model}
                    className="border-b border-border/30 hover:bg-white/[0.02] transition-colors"
                  >
                    <td className="px-6 py-3 font-medium text-foreground">{row.model}</td>
                    <td className="px-6 py-3 tabular-nums">{fmtG(row.estimated_gco2e)}</td>
                    <td
                      className={`px-6 py-3 tabular-nums ${
                        savedPositive
                          ? "text-emerald-400"
                          : row.saved_gco2e < 0
                            ? "text-rose-400"
                            : "text-muted-foreground"
                      }`}
                    >
                      {row.saved_gco2e === 0
                        ? "—"
                        : `${savedPositive ? "" : "−"}${fmtG(Math.abs(row.saved_gco2e))}`}
                    </td>
                    <td className="px-6 py-3">
                      <div className="flex items-center gap-3 min-w-[140px]">
                        <div className="flex-1 h-2 rounded-full bg-muted/60 overflow-hidden">
                          <motion.div
                            className={`h-full rounded-full ${
                              savedPositive ? "bg-sky-500/80" : "bg-rose-500/70"
                            }`}
                            initial={{ width: 0 }}
                            animate={{
                              width: `${reductionAbs}%`,
                            }}
                            transition={{ duration: 0.6, ease: "easeOut" }}
                          />
                        </div>
                        <span className="tabular-nums w-14 text-right text-foreground/90">
                          {`${fmtG(row.reduction_percent, 1)}%`}
                        </span>
                      </div>
                    </td>
                  </tr>
                  )
                })}
                <tr className="bg-green-500/15 border-t border-green-500/30">
                  <td className="px-6 py-4">
                    <div className="flex items-start gap-2">
                      <Leaf className="w-5 h-5 text-green-400 mt-0.5 shrink-0" />
                      <div>
                        <p className="font-bold text-green-300">{system.name}</p>
                        <p className="text-xs text-green-400/80">
                          {system.tagline || "Smart Carbon-Aware Routing"}
                        </p>
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-4 font-bold tabular-nums text-green-300">
                    {fmtG(system.carbon)}
                  </td>
                  <td className="px-6 py-4 text-muted-foreground">—</td>
                  <td className="px-6 py-4 font-bold text-green-300">—</td>
                </tr>
              </tbody>
            </table>
          </div>
        </Card>

        <Card className="p-6 border-border/50 bg-gradient-to-br from-card to-card/40">
          <div className="mb-4">
            <h3 className="font-semibold">Estimated CO₂ by model</h3>
            <p className="text-sm text-muted-foreground">
              Sorted highest to lowest. Our system highlighted in green.
            </p>
          </div>
          <ChartFrame height={360}>
            <BarChart
              data={chartData}
              layout="vertical"
              margin={{ top: 8, right: 28, left: 4, bottom: 8 }}
            >
              <XAxis
                type="number"
                stroke={CHART_AXIS}
                tick={{ fill: CHART_TICK, fontSize: 12 }}
                tickLine={false}
                axisLine={false}
                unit=" g"
              />
              <YAxis
                type="category"
                dataKey="label"
                width={128}
                stroke={CHART_AXIS}
                tick={{ fill: CHART_TICK, fontSize: 12 }}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip
                cursor={{ fill: "rgba(255,255,255,0.04)" }}
                contentStyle={{
                  background: "hsl(var(--card))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: 8,
                  color: CHART_TICK,
                }}
                labelStyle={{ color: "#f4f4f5" }}
                itemStyle={{ color: CHART_TICK }}
                formatter={(value: number) => [`${fmtG(value)} g CO₂e`, "Estimated"]}
                labelFormatter={(label) => String(label)}
              />
              <Bar dataKey="estimated_gco2e" radius={[0, 6, 6, 0]} barSize={18}>
                {chartData.map((entry) => (
                  <Cell
                    key={entry.model}
                    fill={entry.is_ours ? "#22c55e" : "#94a3b8"}
                    fillOpacity={entry.is_ours ? 0.95 : 0.75}
                  />
                ))}
              </Bar>
            </BarChart>
          </ChartFrame>
        </Card>

        {breakdown ? (
          <Card className="p-6 border-border/50 bg-card/50 space-y-6">
            <div>
              <h3 className="font-semibold">Operational emissions breakdown (Boundary A)</h3>
              <p className="text-sm text-muted-foreground mt-1">
                {breakdown.equation ||
                  "CO₂e = (Σ tokens × J/token × PUE) / 3.6e6 × Electricity Maps intensity"}
              </p>
              <p className="text-xs text-muted-foreground mt-1">{boundaryLabel}</p>
            </div>

            {breakdown.uncertainty?.enabled && breakdown.uncertainty.optimized ? (
              <div className="rounded-lg border border-border/40 px-4 py-3 space-y-1">
                <p className="text-sm font-medium">Document Processing · Optimized CO₂e — Typical</p>
                <p className="text-2xl font-bold tabular-nums">
                  {fmtG(breakdown.uncertainty.optimized.typical_gco2e, 1)} g
                </p>
                <p className="text-sm text-muted-foreground">
                  Range{" "}
                  {fmtG(breakdown.uncertainty.optimized.low_gco2e, 1)} –{" "}
                  {fmtG(breakdown.uncertainty.optimized.high_gco2e, 1)} g
                </p>
              </div>
            ) : null}

            {breakdown.optimized_stages_gco2e ? (
              <div>
                <p className="text-sm font-medium mb-2">Optimized pipeline by stage</p>
                <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3 text-sm">
                  {(
                    [
                      ["Inference", breakdown.optimized_stages_gco2e.inference_gco2e],
                      ["Embeddings", breakdown.optimized_stages_gco2e.embedding_gco2e],
                      ["Parsing", breakdown.optimized_stages_gco2e.parsing_gco2e],
                      ["Chunking", breakdown.optimized_stages_gco2e.chunking_gco2e],
                      ["Retrieval", breakdown.optimized_stages_gco2e.retrieval_gco2e],
                      ["Routing", breakdown.optimized_stages_gco2e.routing_gco2e],
                      ["Infrastructure (PUE)", breakdown.optimized_stages_gco2e.infrastructure_gco2e],
                      ["Total", breakdown.optimized_stages_gco2e.total_gco2e],
                    ] as [string, number | undefined][]
                  ).map(([label, value]) =>
                    value != null ? (
                      <div key={label} className="rounded-lg border border-border/40 px-3 py-2">
                        <p className="text-xs text-muted-foreground">{label}</p>
                        <p className="font-medium tabular-nums mt-0.5">{fmtG(value, 1)} g</p>
                      </div>
                    ) : null
                  )}
                </div>
              </div>
            ) : null}

            {breakdown.routing_impact ? (
              <div>
                <p className="text-sm font-medium mb-2">Routing impact / model distribution</p>
                <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3 text-sm">
                  {(
                    [
                      ["Total Chunks", breakdown.routing_impact.total_chunks],
                      ["Light Chunks", breakdown.routing_impact.light_chunks],
                      ["Medium Chunks", breakdown.routing_impact.medium_chunks],
                      ["Heavy Chunks", breakdown.routing_impact.heavy_chunks],
                      ["Escalated Chunks", breakdown.routing_impact.escalated_chunks],
                      ["Compile Calls", breakdown.routing_impact.compile_calls],
                      [
                        "Saved vs all-heavy map",
                        breakdown.routing_impact.co2e_vs_all_heavy_map_g_saved != null
                          ? `${fmtG(breakdown.routing_impact.co2e_vs_all_heavy_map_g_saved, 1)} g`
                          : undefined,
                      ],
                    ] as [string, string | number | undefined][]
                  ).map(([label, value]) =>
                    value != null ? (
                      <div key={label} className="rounded-lg border border-border/40 px-3 py-2">
                        <p className="text-xs text-muted-foreground">{label}</p>
                        <p className="font-medium tabular-nums mt-0.5">{String(value)}</p>
                      </div>
                    ) : null
                  )}
                </div>
              </div>
            ) : null}

            {chunkRows && chunkRows.length > 0 ? (
              <div>
                <p className="text-sm font-medium mb-2">Chunk breakdown</p>
                <div className="overflow-x-auto rounded-lg border border-border/40">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-muted-foreground border-b border-border/40">
                        <th className="px-3 py-2 font-medium">Chunk</th>
                        <th className="px-3 py-2 font-medium">Tier</th>
                        <th className="px-3 py-2 font-medium">Model</th>
                        <th className="px-3 py-2 font-medium">Tokens</th>
                        <th className="px-3 py-2 font-medium">Energy (kWh)</th>
                        <th className="px-3 py-2 font-medium">CO₂e (g)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {chunkRows.map((row) => (
                        <tr
                          key={row.chunk_index}
                          className="border-b border-border/20 hover:bg-white/[0.02]"
                        >
                          <td className="px-3 py-2 tabular-nums">{row.chunk_index}</td>
                          <td className="px-3 py-2 capitalize">{row.tier}</td>
                          <td className="px-3 py-2 font-mono text-xs truncate max-w-[180px]">
                            {row.model}
                          </td>
                          <td className="px-3 py-2 tabular-nums">
                            {row.map_tokens?.toLocaleString()}
                          </td>
                          <td className="px-3 py-2 tabular-nums">
                            {row.energy_kwh != null
                              ? Number(row.energy_kwh).toExponential(2)
                              : "—"}
                          </td>
                          <td className="px-3 py-2 tabular-nums">
                            {fmtG(row.co2e_g, 3)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : null}

            <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-4 text-sm">
              {[
                ["Input Tokens", breakdown.input_tokens?.toLocaleString()],
                ["Retrieved Context", breakdown.retrieved_context_tokens?.toLocaleString()],
                ["Generated Tokens", breakdown.generated_tokens?.toLocaleString()],
                ["Effective Tokens", breakdown.effective_tokens?.toLocaleString()],
                [
                  "Estimated Baseline Energy",
                  breakdown.baseline_energy_kwh != null
                    ? `${Number(breakdown.baseline_energy_kwh).toFixed(4)} kWh`
                    : undefined,
                ],
                [
                  "Estimated Optimized Energy",
                  breakdown.optimized_energy_kwh != null
                    ? `${Number(breakdown.optimized_energy_kwh).toFixed(4)} kWh`
                    : undefined,
                ],
                [
                  "Grid Carbon Intensity",
                  breakdown.grid_carbon_intensity_gco2_kwh != null
                    ? `${Number(breakdown.grid_carbon_intensity_gco2_kwh).toFixed(0)} gCO₂e/kWh`
                    : undefined,
                ],
                [
                  "PUE",
                  breakdown.pue != null ? String(breakdown.pue) : undefined,
                ],
                [
                  "Estimated Baseline Pipeline",
                  (breakdown.estimated_baseline_pipeline_emissions_g ??
                    breakdown.baseline_co2e_g) != null
                    ? `${Number(
                        breakdown.estimated_baseline_pipeline_emissions_g ??
                          breakdown.baseline_co2e_g
                      ).toFixed(1)} g`
                    : undefined,
                ],
                [
                  "Estimated Optimized Pipeline",
                  (breakdown.estimated_optimized_pipeline_emissions_g ??
                    breakdown.actual_co2e_g) != null
                    ? `${Number(
                        breakdown.estimated_optimized_pipeline_emissions_g ??
                          breakdown.actual_co2e_g
                      ).toFixed(1)} g`
                    : undefined,
                ],
                [
                  "Estimated Carbon Saved",
                  breakdown.carbon_saved_g != null
                    ? `${Number(breakdown.carbon_saved_g) >= 0 ? "" : "−"}${Math.abs(
                        Number(breakdown.carbon_saved_g),
                      ).toFixed(1)} g${
                        breakdown.emissions_direction === "increased"
                          ? " (increased)"
                          : ""
                      }`
                    : undefined,
                ],
                [
                  "Estimated Reduction",
                  breakdown.reduction_percent != null
                    ? `${Number(breakdown.reduction_percent).toFixed(1)}%`
                    : undefined,
                ],
                ["Region", breakdown.grid_zone || undefined],
                [
                  "Last Updated",
                  breakdown.grid_updated_at || breakdown.grid_datetime || undefined,
                ],
              ].map(([label, value]) =>
                value != null ? (
                  <div key={String(label)} className="rounded-lg border border-border/40 px-3 py-2">
                    <p className="text-xs text-muted-foreground">{label}</p>
                    <p className="font-medium tabular-nums mt-0.5">{value}</p>
                  </div>
                ) : null
              )}
            </div>
          </Card>
        ) : null}

        <Accordion type="single" collapsible className="rounded-xl border border-border/50 px-4 bg-card/40">
          <AccordionItem value="methodology" className="border-none">
            <AccordionTrigger className="text-sm font-medium hover:no-underline">
              Carbon Calculation Methodology
            </AccordionTrigger>
            <AccordionContent className="text-sm text-muted-foreground leading-relaxed pb-4 whitespace-pre-line space-y-3">
              {breakdown?.baseline_definition ? (
                <p>
                  <span className="text-foreground font-medium">Baseline: </span>
                  {breakdown.baseline_definition}
                </p>
              ) : null}
              {breakdown?.optimized_definition ? (
                <p>
                  <span className="text-foreground font-medium">Optimized: </span>
                  {breakdown.optimized_definition}
                </p>
              ) : null}
              {sanitizeMethodology(
                breakdown?.assumptions_panel || methodText || DEFAULT_METHODOLOGY,
              )}
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      </motion.section>
    </TooltipProvider>
  )
}
