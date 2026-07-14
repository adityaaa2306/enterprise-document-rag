"use client"

import { Card } from "@/components/ui/card"

type TimelineItem = { stage?: string; duration_ms?: number }
type Dist = {
  light?: number
  medium?: number
  heavy?: number
  light_pct?: number
  medium_pct?: number
  heavy_pct?: number
  total?: number
}
type Budget = {
  budget_g?: number | null
  spent_g?: number | null
  remaining_g?: number | null
  predicted_final_g?: number | null
}
type Hierarchy = {
  depth?: number
  levels?: Array<{
    level?: number
    kind?: string
    node_count?: number
    nodes?: Array<{ id?: string; section_path?: string; preview?: string }>
  }>
}

export type AdaptiveInsights = {
  routing_distribution?: Dist | null
  validation_pass_rate?: number | null
  average_confidence?: number | null
  average_semantic_similarity?: number | null
  carbon_by_agent?: Record<string, number> | null
  latency_by_agent?: Record<string, { total_ms?: number; avg_ms?: number; count?: number }> | null
  hierarchy?: Hierarchy | null
  compile_meta?: { used_heavy?: boolean; medium_first?: boolean; compile_confidence?: number } | null
  carbon_budget?: Budget | null
  processing_timeline?: TimelineItem[] | null
  chunk_routing_sample?: Array<{
    chunk_index?: number
    tier?: string
    reason?: string
    expected_carbon_g?: number
  }> | null
  escalation?: { chunks_escalated?: number; required?: boolean } | null
}

function fmtPct(n?: number | null) {
  if (n == null || Number.isNaN(Number(n))) return "—"
  const v = Number(n)
  return `${(v <= 1 ? v * 100 : v).toFixed(1)}%`
}

function fmtG(n?: number | null) {
  if (n == null || Number.isNaN(Number(n))) return "—"
  return `${Number(n).toFixed(2)} g`
}

export function AdaptivePipelinePanel({ insights }: { insights?: AdaptiveInsights | null }) {
  if (!insights) return null
  const dist = insights.routing_distribution
  const budget = insights.carbon_budget
  const hasDist = dist && (dist.light != null || dist.light_pct != null)
  const hasBudget = budget && (budget.budget_g != null || budget.remaining_g != null)
  const timeline = insights.processing_timeline || []
  const hierarchy = insights.hierarchy
  const sample = insights.chunk_routing_sample || []

  if (!hasDist && !hasBudget && !timeline.length && !hierarchy?.depth && !sample.length) {
    return null
  }

  const lightPct = dist?.light_pct ?? 0
  const medPct = dist?.medium_pct ?? 0
  const heavyPct = dist?.heavy_pct ?? 0
  const esc = insights.escalation?.chunks_escalated ?? 0
  const total = Math.max(1, dist?.total ?? 1)
  const escPct = (esc / total) * 100

  return (
    <Card className="p-5 space-y-4 border-border/50 bg-gradient-to-br from-card to-card/40">
      <div>
        <h3 className="text-lg font-semibold">Adaptive Pipeline</h3>
        <p className="text-xs text-muted-foreground">
          Routing mix, carbon budget, hierarchy, and validation signals for this job.
        </p>
      </div>

      {hasBudget ? (
        <div className="grid grid-cols-2 gap-2 text-sm">
          <div className="rounded-md border border-border/40 px-3 py-2">
            <p className="text-xs text-muted-foreground">Carbon Budget</p>
            <p className="font-semibold tabular-nums">{fmtG(budget?.budget_g)}</p>
          </div>
          <div className="rounded-md border border-border/40 px-3 py-2">
            <p className="text-xs text-muted-foreground">Remaining</p>
            <p className="font-semibold tabular-nums">{fmtG(budget?.remaining_g)}</p>
          </div>
          <div className="rounded-md border border-border/40 px-3 py-2">
            <p className="text-xs text-muted-foreground">Spent / Predicted</p>
            <p className="font-semibold tabular-nums">
              {fmtG(budget?.spent_g)} / {fmtG(budget?.predicted_final_g)}
            </p>
          </div>
          <div className="rounded-md border border-border/40 px-3 py-2">
            <p className="text-xs text-muted-foreground">Compile</p>
            <p className="font-semibold">
              {insights.compile_meta?.used_heavy ? "Heavy (escalated)" : "Medium-first"}
            </p>
          </div>
        </div>
      ) : null}

      {hasDist ? (
        <div className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            Routing distribution
          </p>
          <div className="h-3 w-full overflow-hidden rounded-full bg-muted flex">
            <div className="bg-emerald-500/80 h-full" style={{ width: `${lightPct}%` }} title="Light" />
            <div className="bg-sky-500/80 h-full" style={{ width: `${medPct}%` }} title="Medium" />
            <div className="bg-amber-500/80 h-full" style={{ width: `${heavyPct}%` }} title="Heavy" />
          </div>
          <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
            <span>Light {lightPct.toFixed(1)}%</span>
            <span>Medium {medPct.toFixed(1)}%</span>
            <span>Heavy {heavyPct.toFixed(1)}%</span>
            <span>Escalated {escPct.toFixed(1)}%</span>
          </div>
        </div>
      ) : null}

      <div className="grid grid-cols-2 gap-2 text-sm">
        <div className="rounded-md border border-border/40 px-3 py-2">
          <p className="text-xs text-muted-foreground">Validation pass rate</p>
          <p className="font-semibold tabular-nums">
            {insights.validation_pass_rate != null
              ? `${(Number(insights.validation_pass_rate) * 100).toFixed(1)}%`
              : "—"}
          </p>
        </div>
        <div className="rounded-md border border-border/40 px-3 py-2">
          <p className="text-xs text-muted-foreground">Avg confidence</p>
          <p className="font-semibold tabular-nums">
            {insights.average_confidence != null
              ? Number(insights.average_confidence).toFixed(2)
              : "—"}
          </p>
        </div>
        <div className="rounded-md border border-border/40 px-3 py-2">
          <p className="text-xs text-muted-foreground">Avg semantic sim</p>
          <p className="font-semibold tabular-nums">
            {insights.average_semantic_similarity != null
              ? Number(insights.average_semantic_similarity).toFixed(2)
              : "—"}
          </p>
        </div>
        <div className="rounded-md border border-border/40 px-3 py-2">
          <p className="text-xs text-muted-foreground">Hierarchy depth</p>
          <p className="font-semibold tabular-nums">{hierarchy?.depth ?? "—"}</p>
        </div>
      </div>

      {timeline.length > 0 ? (
        <div className="space-y-1.5">
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            Processing timeline
          </p>
          {timeline.map((t) => (
            <div key={String(t.stage)} className="flex justify-between text-sm gap-3">
              <span className="text-muted-foreground truncate">{t.stage}</span>
              <span className="tabular-nums font-medium">
                {t.duration_ms != null ? `${Number(t.duration_ms).toFixed(0)} ms` : "—"}
              </span>
            </div>
          ))}
        </div>
      ) : null}

      {hierarchy?.levels && hierarchy.levels.length > 0 ? (
        <div className="space-y-1.5">
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            Summary hierarchy
          </p>
          {hierarchy.levels.map((lv) => (
            <div key={`${lv.level}-${lv.kind}`} className="text-sm flex justify-between gap-2">
              <span className="text-muted-foreground">
                L{lv.level} · {lv.kind}
              </span>
              <span className="tabular-nums font-medium">{lv.node_count ?? 0} nodes</span>
            </div>
          ))}
        </div>
      ) : null}

      {sample.length > 0 ? (
        <div className="space-y-1.5">
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            Chunk routing (sample)
          </p>
          <div className="max-h-40 overflow-auto space-y-1.5 pr-1">
            {sample.map((r) => (
              <div key={r.chunk_index} className="text-xs border-b border-border/30 pb-1">
                <span className="font-medium">#{r.chunk_index}</span>{" "}
                <span className="text-emerald-400">{r.tier}</span>
                <p className="text-muted-foreground leading-snug">{r.reason}</p>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {insights.carbon_by_agent && Object.keys(insights.carbon_by_agent).length > 0 ? (
        <div className="space-y-1">
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            Est. carbon by agent
          </p>
          {Object.entries(insights.carbon_by_agent).map(([tier, g]) => (
            <div key={tier} className="flex justify-between text-sm">
              <span className="text-muted-foreground capitalize">{tier}</span>
              <span className="tabular-nums">{fmtG(g)}</span>
            </div>
          ))}
        </div>
      ) : null}
    </Card>
  )
}
