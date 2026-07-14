"use client"

import { useMemo, useState, type ComponentType } from "react"
import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import {
  ChevronDown,
  Gauge,
  Globe2,
  Layers,
  Leaf,
  Scale,
  TrendingDown,
} from "lucide-react"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { DocumentStructureViewer } from "@/components/document-structure-viewer"
import {
  extractCompactMetrics,
  fmtG,
  fmtIntensity,
  fmtPct,
  type CompactJobMetrics,
} from "@/lib/job-results-metrics"
import { cn } from "@/lib/utils"

type Props = {
  result: {
    carbon_data?: Record<string, unknown> | null
    processing_insights?: Record<string, unknown> | null
    final_summary?: string
    comparison_models?: unknown
    our_system?: unknown
    summary_cards?: unknown
    chart_bars?: unknown
    methodology?: string | null
  }
}

function HeroTile({
  label,
  value,
  subtext,
  icon: Icon,
  valueClassName,
}: {
  label: string
  value: string
  subtext?: string
  icon: ComponentType<{ className?: string }>
  valueClassName?: string
}) {
  return (
    <div className="rounded-lg bg-muted/30 border border-border/40 px-3 py-3 min-w-0">
      <div className="flex items-center gap-1.5 text-muted-foreground mb-1">
        <Icon className="w-3.5 h-3.5 shrink-0" />
        <span className="text-[11px] uppercase tracking-wide truncate">{label}</span>
      </div>
      <p className={cn("text-lg font-bold tabular-nums truncate", valueClassName)}>{value}</p>
      {subtext ? (
        <p className="text-[11px] text-muted-foreground mt-0.5 truncate">{subtext}</p>
      ) : null}
    </div>
  )
}

function StackedBar({
  segments,
  className,
}: {
  segments: Array<{ key: string; label: string; value: number; className: string }>
  className?: string
}) {
  const total = segments.reduce((s, x) => s + Math.max(0, x.value), 0)
  const positive = segments.filter((s) => s.value > 1e-9)
  if (total <= 0 || positive.length === 0) {
    return (
      <div className={cn("h-3 rounded-full bg-muted", className)} title="No data" />
    )
  }
  return (
    <div className={cn("h-3 rounded-full overflow-hidden flex bg-muted", className)}>
      {positive.map((s) => (
        <div
          key={s.key}
          className={cn("h-full", s.className)}
          style={{ width: `${(s.value / total) * 100}%` }}
          title={`${s.label}: ${s.value.toFixed(2)}`}
        />
      ))}
    </div>
  )
}

const COLOR_BASELINE = "#F4F4F5"
const COLOR_OURS = "#34D399"
/** Peer model bars — dark gray for contrast on black chart bg */
const COLOR_PEER_BAR = "#52525B"
const COLOR_MUTED_TICK = "#A1A1AA"
const COLOR_CHART_AXIS = "#71717A"

function CompareBar({
  label,
  value,
  max,
  tone,
}: {
  label: string
  value: number
  max: number
  tone: "baseline" | "optimized"
}) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0
  return (
    <div className="space-y-1">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="h-2.5 rounded-full bg-muted overflow-hidden">
        <div
          className="h-full rounded-full transition-all"
          style={{
            width: `${pct}%`,
            backgroundColor: tone === "baseline" ? COLOR_BASELINE : COLOR_OURS,
          }}
          aria-label={`${label} relative bar`}
        />
      </div>
    </div>
  )
}

function tierBadgeClass(tier: string) {
  const t = tier.toLowerCase()
  if (t === "light") return "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
  if (t === "heavy") return "bg-rose-500/15 text-rose-300 border-rose-500/30"
  return "bg-sky-500/15 text-sky-300 border-sky-500/30"
}

function EmissionsTab({ m }: { m: CompactJobMetrics }) {
  const stages = m.optimizedStages || {}
  const inference = Number(stages.inference_gco2e || 0)
  const infra = Number(stages.infrastructure_gco2e || 0)
  const nearZero = [
    { label: "Embeddings", v: Number(stages.embedding_gco2e || 0) },
    { label: "Parsing", v: Number(stages.parsing_gco2e || 0) },
    { label: "Chunking", v: Number(stages.chunking_gco2e || 0) },
    { label: "Retrieval", v: Number(stages.retrieval_gco2e || 0) },
    { label: "Routing", v: Number(stages.routing_gco2e || 0) },
    { label: "Verification", v: Number(stages.verification_gco2e || 0) },
  ].filter((x) => x.v <= 1e-6)
  const barMax = Math.max(m.baselineG, m.optimizedG, 1e-9)

  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <p className="text-xs font-medium text-muted-foreground">Stage breakdown (optimized)</p>
        <StackedBar
          segments={[
            {
              key: "inf",
              label: "Inference",
              value: inference,
              className: "bg-emerald-400",
            },
            {
              key: "infra",
              label: "Infrastructure",
              value: infra,
              className: "bg-emerald-400/40",
            },
          ]}
        />
        <div className="flex flex-wrap gap-3 text-[11px] text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-sm bg-emerald-400" /> Inference {fmtG(inference)}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-sm bg-emerald-400/40" /> Infrastructure {fmtG(infra)}
          </span>
        </div>
        {nearZero.length > 0 ? (
          <p className="text-[11px] text-muted-foreground">
            {nearZero.map((x) => x.label).join(", ")}: ~0 g
          </p>
        ) : null}
      </div>

      <div className="space-y-2">
        <p className="text-xs font-medium text-muted-foreground">Baseline vs optimized</p>
        <CompareBar label="Baseline" value={m.baselineG} max={barMax} tone="baseline" />
        <CompareBar label="Optimized" value={m.optimizedG} max={barMax} tone="optimized" />
      </div>

      <div className="flex flex-wrap gap-2">
        {(
          [
            ["Input", m.tokens.input],
            ["Retrieved", m.tokens.retrieved],
            ["Generated", m.tokens.generated],
            ["Effective", m.tokens.effective],
          ] as const
        ).map(([label, n]) => (
          <span
            key={label}
            className="inline-flex items-center gap-1.5 rounded-md border border-border/50 bg-muted/20 px-2.5 py-1 text-xs"
          >
            <span className="text-muted-foreground">{label}</span>
            <span className="font-medium tabular-nums">{n.toLocaleString()}</span>
          </span>
        ))}
      </div>

      <p className="font-mono text-[11px] text-muted-foreground leading-relaxed break-words">
        {m.equation}
      </p>
    </div>
  )
}

function RoutingTab({ m }: { m: CompactJobMetrics }) {
  const { light, medium, heavy, escalated } = m.tierMix
  const rows = m.chunkBreakdown.length
    ? m.chunkBreakdown
    : m.chunkRoutingSample.map((r) => ({
        chunk_index: r.chunk_index,
        tier: r.tier,
        map_tokens: undefined,
        input_tokens: undefined,
        co2e_g: undefined,
      }))

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <p className="text-xs font-medium text-muted-foreground">Tier distribution</p>
        <StackedBar
          segments={[
            { key: "l", label: "Light", value: light, className: "bg-emerald-500/70" },
            { key: "m", label: "Medium", value: medium, className: "bg-sky-500/70" },
            { key: "h", label: "Heavy", value: heavy, className: "bg-rose-500/70" },
          ]}
        />
        <div className="flex flex-wrap gap-3 text-[11px] text-muted-foreground">
          <span>Light {light}</span>
          <span>Medium {medium}</span>
          <span>Heavy {heavy}</span>
        </div>
      </div>

      <p className="text-xs text-muted-foreground">
        Escalations: {escalated} chunk{escalated === 1 ? "" : "s"}
      </p>

      <div className="rounded-lg border border-border/40 overflow-hidden">
        <div className="max-h-64 overflow-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-card border-b border-border/40 text-muted-foreground">
              <tr>
                <th className="text-left font-medium px-3 py-2">Chunk #</th>
                <th className="text-left font-medium px-3 py-2">Tier</th>
                <th className="text-right font-medium px-3 py-2">Tokens</th>
                <th className="text-right font-medium px-3 py-2">CO₂e</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-3 py-4 text-muted-foreground">
                    No chunk routing rows available.
                  </td>
                </tr>
              ) : (
                rows.map((row, idx) => {
                  const tier = String(row.tier || "—")
                  const tokens = Number(
                    (row as { map_tokens?: number }).map_tokens ??
                      (row as { input_tokens?: number }).input_tokens ??
                      0,
                  )
                  const co2 = Number((row as { co2e_g?: number }).co2e_g)
                  return (
                    <tr
                      key={`${row.chunk_index ?? idx}`}
                      className="border-b border-border/20 last:border-0"
                    >
                      <td className="px-3 py-1.5 tabular-nums">{row.chunk_index ?? idx}</td>
                      <td className="px-3 py-1.5">
                        <span
                          className={cn(
                            "inline-flex rounded border px-1.5 py-0.5 capitalize",
                            tierBadgeClass(tier),
                          )}
                        >
                          {tier}
                        </span>
                      </td>
                      <td className="px-3 py-1.5 text-right tabular-nums">
                        {tokens ? tokens.toLocaleString() : "—"}
                      </td>
                      <td className="px-3 py-1.5 text-right tabular-nums">
                        {Number.isFinite(co2) ? fmtG(co2, 2) : "—"}
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function shortModelLabel(name: string, isOurs?: boolean) {
  if (isOurs) return "Ours (Green Agentic)"
  if (name.length <= 22) return name
  return `${name.slice(0, 20)}…`
}

function ModelComparisonTab({ m }: { m: CompactJobMetrics }) {
  const data = [...m.modelBars]
    .sort((a, b) => Number(b.estimated_gco2e) - Number(a.estimated_gco2e))
    .map((row) => ({
      ...row,
      label: shortModelLabel(
        String(row.model || ""),
        Boolean(row.is_ours) ||
          /green\s*agentic/i.test(String(row.model || "")),
      ),
    }))
  if (!data.length) {
    return (
      <p className="text-sm text-muted-foreground">No frontier comparison data for this job.</p>
    )
  }
  return (
    <div className="h-[320px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ left: 8, right: 16, top: 8, bottom: 8 }}>
          <XAxis
            type="number"
            tick={{ fontSize: 11, fill: COLOR_MUTED_TICK }}
            stroke={COLOR_CHART_AXIS}
          />
          <YAxis
            type="category"
            dataKey="label"
            width={132}
            tick={{ fontSize: 11, fill: COLOR_MUTED_TICK }}
            stroke={COLOR_CHART_AXIS}
          />
          <Tooltip
            contentStyle={{
              background: "#18181B",
              border: "1px solid #27272A",
              borderRadius: 8,
              fontSize: 12,
              color: "#FAFAFA",
            }}
            formatter={(value: number) => [`${Number(value).toFixed(1)} g`, "CO₂e"]}
            labelFormatter={(_, payload) => {
              const row = payload?.[0]?.payload as { model?: string } | undefined
              return row?.model || ""
            }}
          />
          <Bar dataKey="estimated_gco2e" radius={[0, 4, 4, 0]}>
            {data.map((entry) => {
              const isOurs =
                Boolean(entry.is_ours) ||
                /green\s*agentic|ours \(green/i.test(String(entry.model || ""))
              return (
                <Cell
                  key={entry.model}
                  fill={isOurs ? COLOR_OURS : COLOR_PEER_BAR}
                />
              )
            })}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function RegionStrategyTab({ m }: { m: CompactJobMetrics }) {
  const rows: [string, string][] = [
    ["Region", m.region],
    ["Grid intensity", fmtIntensity(m.intensityGco2Kwh)],
    [
      "Provider",
      m.provider === "electricity_maps" ? "Electricity Maps" : m.provider || "—",
    ],
    [
      "Scheduling mode",
      (m.schedulingMode || "single-region").replace(/_/g, " ").replace(/-/g, " "),
    ],
    ["Document type", String(m.documentType || "—")],
    ["Complexity", m.complexity != null ? String(m.complexity) : "—"],
    [
      "Strategy",
      String(
        (m.strategy?.strategy_id as string) ||
          (m.strategy?.map_mode as string) ||
          "—",
      ),
    ],
    [
      "Confidence / accuracy",
      m.accuracyEstimate != null
        ? fmtPct(m.accuracyEstimate <= 1 ? m.accuracyEstimate * 100 : m.accuracyEstimate)
        : m.confidence != null
          ? fmtPct(m.confidence <= 1 ? m.confidence * 100 : m.confidence)
          : "—",
    ],
  ]

  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3 text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="min-w-0">
            <dt className="text-xs text-muted-foreground">{k}</dt>
            <dd className="font-medium truncate">{v}</dd>
          </div>
        ))}
      </dl>
      <p className="text-xs text-muted-foreground">
        Multi-region scheduling isn&apos;t active yet — this run used the configured
        execution region only.
      </p>
    </div>
  )
}

function DeveloperTrace({ m }: { m: CompactJobMetrics }) {
  const [open, setOpen] = useState(false)
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <div className="rounded-lg border border-border/40 bg-muted/10">
        <CollapsibleTrigger className="flex w-full items-center justify-between px-4 py-3 text-sm font-medium hover:bg-muted/20 transition-colors">
          <span>Developer trace</span>
          <ChevronDown
            className={cn("w-4 h-4 text-muted-foreground transition-transform", open && "rotate-180")}
          />
        </CollapsibleTrigger>
        <CollapsibleContent className="px-4 pb-4 space-y-4 border-t border-border/30">
          {m.reasonSummary ? (
            <div className="pt-3 space-y-1">
              <p className="text-xs font-medium text-muted-foreground">Why this model was selected</p>
              <p className="text-sm leading-relaxed">{m.reasonSummary}</p>
              {m.selectedModel ? (
                <p className="text-xs text-muted-foreground">Model: {m.selectedModel}</p>
              ) : null}
            </div>
          ) : null}

          {m.chunkRoutingSample.length > 0 ? (
            <div className="space-y-2">
              <p className="text-xs font-medium text-muted-foreground">Per-chunk routing reasoning</p>
              <ul className="space-y-2 max-h-48 overflow-auto text-xs">
                {m.chunkRoutingSample.map((row, i) => (
                  <li
                    key={`${row.chunk_index ?? i}`}
                    className="rounded border border-border/30 px-2.5 py-2"
                  >
                    <span className="font-medium">
                      Chunk {row.chunk_index ?? i} · {row.tier || "—"}
                    </span>
                    <p className="text-muted-foreground mt-0.5">{row.reason || "—"}</p>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {m.timeline.length > 0 ? (
            <div className="space-y-2">
              <p className="text-xs font-medium text-muted-foreground">Latency by stage</p>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-xs">
                {m.timeline.map((t, i) => (
                  <div
                    key={`${t.stage}-${i}`}
                    className="rounded border border-border/30 px-2 py-1.5 flex justify-between gap-2"
                  >
                    <span className="text-muted-foreground truncate">{t.stage || "stage"}</span>
                    <span className="tabular-nums font-medium">
                      {Math.round(Number(t.duration_ms) || 0)} ms
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {(m.documentTree && m.documentTree.length > 0) ||
          (m.structureDiagnostics && Object.keys(m.structureDiagnostics).length > 0) ? (
            <DocumentStructureViewer
              tree={m.documentTree as any}
              diagnostics={m.structureDiagnostics as any}
            />
          ) : null}
        </CollapsibleContent>
      </div>
    </Collapsible>
  )
}

export function JobResultsPanel({ result }: Props) {
  const metrics = useMemo(
    () => extractCompactMetrics(result as Parameters<typeof extractCompactMetrics>[0]),
    [result],
  )

  const tierSub = `L ${metrics.tierMix.light} · M ${metrics.tierMix.medium} · H ${metrics.tierMix.heavy}`

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3">
        <HeroTile
          label="Optimized CO₂e"
          value={fmtG(metrics.optimizedG)}
          icon={Leaf}
        />
        <HeroTile
          label="Baseline CO₂e"
          value={fmtG(metrics.baselineG)}
          icon={Scale}
        />
        <HeroTile
          label={metrics.emissionsIncreased ? "Emissions Δ" : "Carbon saved"}
          value={fmtG(Math.abs(metrics.savedG))}
          icon={TrendingDown}
          valueClassName={metrics.emissionsIncreased ? "text-rose-400" : undefined}
        />
        <HeroTile
          label="Reduction"
          value={fmtPct(metrics.reductionPct)}
          icon={Gauge}
          valueClassName={metrics.emissionsIncreased ? "text-rose-400" : undefined}
        />
        <HeroTile
          label="Region"
          value={metrics.region}
          subtext={fmtIntensity(metrics.intensityGco2Kwh)}
          icon={Globe2}
        />
        <HeroTile
          label="Chunks"
          value={String(metrics.totalChunks)}
          subtext={tierSub}
          icon={Layers}
        />
      </div>

      <div className="rounded-lg border border-border/40 bg-card/40 p-4">
        <Tabs defaultValue="emissions" className="w-full">
          <TabsList className="grid w-full grid-cols-2 sm:grid-cols-4 h-auto gap-1">
            <TabsTrigger value="emissions">Emissions</TabsTrigger>
            <TabsTrigger value="routing">Routing</TabsTrigger>
            <TabsTrigger value="models">Model comparison</TabsTrigger>
            <TabsTrigger value="region">Region & strategy</TabsTrigger>
          </TabsList>
          <TabsContent value="emissions" className="pt-4">
            <EmissionsTab m={metrics} />
          </TabsContent>
          <TabsContent value="routing" className="pt-4">
            <RoutingTab m={metrics} />
          </TabsContent>
          <TabsContent value="models" className="pt-4">
            <ModelComparisonTab m={metrics} />
          </TabsContent>
          <TabsContent value="region" className="pt-4">
            <RegionStrategyTab m={metrics} />
          </TabsContent>
        </Tabs>
      </div>

      <DeveloperTrace m={metrics} />
    </div>
  )
}
