"use client"

import { Card } from "@/components/ui/card"
import { Brain, Leaf, Gauge, Layers, AlertTriangle } from "lucide-react"

export interface ProcessingInsightsData {
  crs?: number | null
  document_type?: string | null
  selected_model?: string | null
  tier?: string | null
  compile_tier?: string | null
  retrieval_strategy?: string | null
  escalation?: {
    required?: boolean
    chunks_escalated?: number
    details?: unknown[]
  } | null
  carbon_optimization_applied?: boolean
  latency_ms?: number | null
  confidence?: number | null
  reason_summary?: string | null
  routing_preference?: string | null
  domain_risk?: Record<string, unknown> | null
  policy_version?: string | null
  min_tier?: string | null
}

function formatPreference(pref?: string | null) {
  if (!pref) return "Automatic"
  return pref
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

interface ProcessingInsightsProps {
  insights?: ProcessingInsightsData | null
}

export function ProcessingInsightsPanel({ insights }: ProcessingInsightsProps) {
  if (!insights) {
    return (
      <Card className="p-5 bg-card/40 border-border/50">
        <h3 className="text-sm font-semibold mb-2">Processing Insights</h3>
        <p className="text-xs text-muted-foreground">
          Insights will appear when the job completes.
        </p>
      </Card>
    )
  }

  const escalation = insights.escalation

  return (
    <Card className="p-5 bg-card/40 border-border/50 space-y-4">
      <div>
        <h3 className="text-sm font-semibold mb-1">Processing Insights</h3>
        <p className="text-xs text-muted-foreground">
          How Smart Routing chose models for this document
        </p>
      </div>

      {insights.reason_summary ? (
        <div className="rounded-lg bg-primary/10 border border-primary/20 p-3">
          <p className="text-xs text-muted-foreground mb-1">Why this model was selected</p>
          <p className="text-sm leading-relaxed">{insights.reason_summary}</p>
        </div>
      ) : null}

      <div className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <p className="text-xs text-muted-foreground">Selected model</p>
          <p className="font-medium truncate" title={insights.selected_model || undefined}>
            {insights.selected_model || "—"}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Tier</p>
          <p className="font-medium">{insights.tier || "—"}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground flex items-center gap-1">
            <Brain className="w-3 h-3" /> CRS
          </p>
          <p className="font-medium">
            {insights.crs != null ? insights.crs.toFixed(2) : "—"}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Document type</p>
          <p className="font-medium">{insights.document_type || "—"}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Routing preference</p>
          <p className="font-medium">{formatPreference(insights.routing_preference)}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground flex items-center gap-1">
            <Layers className="w-3 h-3" /> Retrieval
          </p>
          <p className="font-medium text-xs leading-snug">
            {insights.retrieval_strategy || "Hybrid Dense + Sparse + Reranking"}
          </p>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 text-xs">
        {insights.carbon_optimization_applied ? (
          <span className="inline-flex items-center gap-1 px-2 py-1 rounded bg-green-500/15 text-green-400">
            <Leaf className="w-3 h-3" /> Carbon optimization applied
          </span>
        ) : null}
        {insights.latency_ms != null ? (
          <span className="inline-flex items-center gap-1 px-2 py-1 rounded bg-blue-500/15 text-blue-300">
            <Gauge className="w-3 h-3" /> {Math.round(insights.latency_ms)} ms
          </span>
        ) : null}
        {insights.confidence != null ? (
          <span className="inline-flex items-center gap-1 px-2 py-1 rounded bg-amber-500/15 text-amber-300">
            Confidence {(insights.confidence * 100).toFixed(0)}%
          </span>
        ) : null}
        {escalation?.required ? (
          <span className="inline-flex items-center gap-1 px-2 py-1 rounded bg-orange-500/15 text-orange-300">
            <AlertTriangle className="w-3 h-3" />
            Escalation
            {escalation.chunks_escalated
              ? ` (${escalation.chunks_escalated} chunks)`
              : ""}
          </span>
        ) : null}
      </div>
    </Card>
  )
}
