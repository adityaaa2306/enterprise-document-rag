"use client"

import type { ReactNode } from "react"
import { Card } from "@/components/ui/card"
import { cn } from "@/lib/utils"

type Profile = {
  pages_estimate?: number
  estimated_tokens?: number
  semantic_sections?: number
  chunk_count?: number
  average_section_tokens?: number
  largest_section_tokens?: number
  table_count?: number
  figure_count?: number
  equation_count?: number
  reading_level?: number
  technical_density?: number
  layout_complexity?: number
  heading_depth?: number
  document_scale?: string
  complexity_class?: string
}

type Strategy = {
  strategy_id?: string
  map_mode?: string
  compile_depth_label?: string
  hierarchy_fan_in?: number
  hierarchy_max_depth?: number
  verification_strategy?: string
  max_escalations?: number
  carbon_budget_g?: number
  reasons?: string[]
}

type Report = {
  why_chunk_sizes?: string
  why_strategy?: string[]
  why_models?: string
  why_compile_depth?: string
  estimated_carbon_g?: number
  estimated_latency_s?: number
  estimated_map_api_calls?: number
  expected_quality?: number
  accuracy_estimate?: number
  routing_mix?: { light?: number; medium?: number; heavy?: number }
  carbon_intensity_gco2_kwh?: number
}

export type PipelineIntelligenceData = {
  capability_profile?: Profile | null
  strategy?: Strategy | null
  report?: Report | null
  policy_version?: string
}

function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="rounded-md bg-muted/40 px-2.5 py-2">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-0.5 text-sm font-medium text-foreground">{value ?? "—"}</p>
    </div>
  )
}

export function PipelineIntelligencePanel({
  insights,
  className,
}: {
  insights?: {
    pipeline_intelligence?: PipelineIntelligenceData | null
    document_profile?: Profile | null
    processing_strategy?: Strategy | null
    intelligence_report?: Report | null
    routing_distribution?: {
      light?: number
      medium?: number
      heavy?: number
      total?: number
    } | null
    escalation?: { chunks_escalated?: number; required?: boolean } | null
    hierarchy?: { depth?: number } | null
    compile_meta?: { used_heavy?: boolean; hierarchy_depth?: number } | null
    validation_pass_rate?: number | null
    average_confidence?: number | null
    carbon_budget?: {
      budget_g?: number | null
      spent_g?: number | null
    } | null
    processing_timeline?: Array<{ stage?: string; duration_ms?: number }> | null
  } | null
  className?: string
}) {
  const intel = insights?.pipeline_intelligence
  const profile = intel?.capability_profile || insights?.document_profile || null
  const strategy = intel?.strategy || insights?.processing_strategy || null
  const report = intel?.report || insights?.intelligence_report || null
  const dist = insights?.routing_distribution
  const timeline = insights?.processing_timeline || []

  if (!profile && !strategy && !report) return null

  return (
    <Card className={cn("p-6 bg-card/50 border-border/50 space-y-4", className)}>
      <div>
        <h3 className="text-lg font-semibold">Pipeline Intelligence</h3>
        <p className="text-xs text-muted-foreground mt-1">
          Adaptive strategy chosen from document capability + carbon context
        </p>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <Stat label="Document scale" value={profile?.document_scale} />
        <Stat label="Complexity" value={profile?.complexity_class} />
        <Stat label="Strategy" value={strategy?.strategy_id} />
        <Stat label="Map mode" value={strategy?.map_mode} />
        <Stat label="Compile depth" value={strategy?.compile_depth_label} />
        <Stat
          label="Hierarchy"
          value={
            insights?.hierarchy?.depth ??
            insights?.compile_meta?.hierarchy_depth ??
            strategy?.hierarchy_max_depth
          }
        />
        <Stat label="Chunks" value={profile?.chunk_count} />
        <Stat label="Est. tokens" value={profile?.estimated_tokens} />
        <Stat label="Pages (est.)" value={profile?.pages_estimate} />
        <Stat label="Tables / figures" value={`${profile?.table_count ?? 0} / ${profile?.figure_count ?? 0}`} />
        <Stat
          label="Model mix L/M/H"
          value={`${dist?.light ?? report?.routing_mix?.light ?? 0}/${dist?.medium ?? report?.routing_mix?.medium ?? 0}/${dist?.heavy ?? report?.routing_mix?.heavy ?? 0}`}
        />
        <Stat
          label="Escalations"
          value={insights?.escalation?.chunks_escalated ?? 0}
        />
        <Stat
          label="Validation"
          value={
            insights?.average_confidence != null
              ? `${(Number(insights.average_confidence) <= 1 ? Number(insights.average_confidence) * 100 : Number(insights.average_confidence)).toFixed(0)}% conf`
              : "—"
          }
        />
        <Stat
          label="Accuracy estimate"
          value={
            report?.accuracy_estimate != null
              ? `${(Number(report.accuracy_estimate) * 100).toFixed(0)}%`
              : "—"
          }
        />
        <Stat
          label="Est. map carbon"
          value={report?.estimated_carbon_g != null ? `${report.estimated_carbon_g} g` : "—"}
        />
        <Stat
          label="Est. map latency"
          value={report?.estimated_latency_s != null ? `${report.estimated_latency_s}s` : "—"}
        />
      </div>

      {strategy?.reasons && strategy.reasons.length > 0 ? (
        <div>
          <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground mb-1">
            Why this strategy
          </p>
          <ul className="list-disc pl-4 text-xs text-foreground/90 space-y-0.5">
            {strategy.reasons.slice(0, 8).map((r, i) => (
              <li key={`${r}-${i}`}>{r}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {report?.why_chunk_sizes ? (
        <p className="text-xs text-muted-foreground leading-relaxed">{report.why_chunk_sizes}</p>
      ) : null}

      {timeline.length > 0 ? (
        <div>
          <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground mb-1">
            Latency by stage
          </p>
          <div className="space-y-1 max-h-40 overflow-auto">
            {timeline.map((t, i) => (
              <div
                key={`${t.stage}-${i}`}
                className="flex justify-between text-[11px] font-mono text-muted-foreground"
              >
                <span>{t.stage}</span>
                <span>{t.duration_ms != null ? `${(t.duration_ms / 1000).toFixed(2)}s` : "—"}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </Card>
  )
}
