/**
 * Presentation helpers — pull display metrics from existing job result payloads.
 * Does not recompute carbon; only resolves field precedence for the UI.
 */

import {
  resolveFrontierComparison,
  type ChunkBreakdownRow,
  type FrontierComparisonPayload,
} from "@/lib/frontier-carbon-compare"

export type StageEmissions = {
  parsing_gco2e?: number
  chunking_gco2e?: number
  embedding_gco2e?: number
  retrieval_gco2e?: number
  routing_gco2e?: number
  inference_gco2e?: number
  verification_gco2e?: number
  infrastructure_gco2e?: number
  total_gco2e?: number
  [key: string]: number | undefined
}

export type CompactJobMetrics = {
  baselineG: number
  optimizedG: number
  savedG: number
  reductionPct: number
  emissionsIncreased: boolean
  region: string
  intensityGco2Kwh: number
  totalChunks: number
  tierMix: { light: number; medium: number; heavy: number; escalated: number }
  tokens: {
    input: number
    retrieved: number
    generated: number
    effective: number
  }
  equation: string
  optimizedStages: StageEmissions | null
  baselineStages: StageEmissions | null
  chunkBreakdown: ChunkBreakdownRow[]
  chunkRoutingSample: Array<{
    chunk_index?: number
    tier?: string
    reason?: string
    model?: string
  }>
  modelBars: Array<{ model: string; estimated_gco2e: number; is_ours: boolean }>
  frontier: FrontierComparisonPayload | null
  regionDecision: Record<string, unknown> | null
  strategy: Record<string, unknown> | null
  documentProfile: Record<string, unknown> | null
  reasonSummary: string | null
  timeline: Array<{ stage?: string; duration_ms?: number }>
  documentTree: unknown[] | null
  structureDiagnostics: Record<string, unknown> | null
  selectedModel: string | null
  documentType: string | null
  complexity: string | number | null
  accuracyEstimate: number | null
  confidence: number | null
  schedulingMode: string | null
  provider: string | null
}

function asRecord(raw: unknown): Record<string, unknown> {
  if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    return raw as Record<string, unknown>
  }
  if (typeof raw === "string") {
    try {
      const parsed = JSON.parse(raw)
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        return parsed as Record<string, unknown>
      }
    } catch {
      /* ignore */
    }
  }
  return {}
}

function numOr(...vals: unknown[]): number | undefined {
  for (const v of vals) {
    if (v == null || v === "") continue
    const n = Number(v)
    if (Number.isFinite(n)) return n
  }
  return undefined
}

function stageOf(raw: unknown): StageEmissions | null {
  const r = asRecord(raw)
  if (!Object.keys(r).length) return null
  return r as StageEmissions
}

const DEFAULT_EQUATION =
  "CO₂e(g) = (Σ tokens×J/token × PUE × INFRASTRUCTURE_FACTOR / 3_600_000) × grid_intensity_gCO₂e/kWh"

export function fmtG(n: number | undefined | null, digits = 1): string {
  if (n == null || !Number.isFinite(Number(n))) return "—"
  return `${Number(n).toFixed(digits)} g`
}

export function fmtPct(n: number | undefined | null, digits = 1): string {
  if (n == null || !Number.isFinite(Number(n))) return "—"
  return `${Number(n).toFixed(digits)}%`
}

export function fmtIntensity(n: number | undefined | null): string {
  if (n == null || !Number.isFinite(Number(n))) return "—"
  return `${Math.round(Number(n))} gCO₂e/kWh`
}

export function extractCompactMetrics(result: {
  carbon_data?: Record<string, unknown> | null
  processing_insights?: Record<string, unknown> | null
  final_summary?: string
  comparison_models?: unknown
  our_system?: unknown
  summary_cards?: unknown
  chart_bars?: unknown
  methodology?: string | null
}): CompactJobMetrics {
  const cd = asRecord(result.carbon_data)
  const rc = asRecord(cd.report_card)
  const bd = { ...asRecord(cd.breakdown), ...rc }
  const insights = asRecord(result.processing_insights)
  const intel = asRecord(insights.pipeline_intelligence)
  const profile = asRecord(intel.capability_profile || insights.document_profile)
  const strategy = asRecord(intel.strategy || insights.processing_strategy)
  const report = asRecord(intel.report || insights.intelligence_report)
  const routingImpact = asRecord(bd.routing_impact || cd.routing_impact)
  const dist = asRecord(insights.routing_distribution)
  const regionDecision = asRecord(cd.region_decision)
  const regionObj = asRecord(regionDecision.selected_region)

  const baselineG =
    numOr(
      rc.estimated_baseline_pipeline_emissions_g,
      cd.estimated_baseline_pipeline_emissions_g,
      bd.estimated_baseline_pipeline_emissions_g,
      bd.baseline_co2e_g,
      cd.baseline_cost_gco2e,
    ) ?? 0
  const optimizedG =
    numOr(
      cd.operational_co2e_g,
      rc.estimated_optimized_pipeline_emissions_g,
      cd.estimated_optimized_pipeline_emissions_g,
      bd.estimated_optimized_pipeline_emissions_g,
      bd.actual_co2e_g,
      cd.actual_cost_gco2e,
    ) ?? 0
  const modeledG = numOr(cd.modeled_co2e_g) ?? null
  const savedG = numOr(bd.carbon_saved_g, cd.carbon_saved_grams, baselineG - (modeledG ?? optimizedG)) ?? 0
  const reductionPct = numOr(bd.reduction_percent, cd.efficiency_percent, 0) ?? 0
  const emissionsIncreased =
    bd.emissions_direction === "increased" ||
    cd.emissions_direction === "increased" ||
    savedG < 0

  const intensity =
    numOr(
      regionDecision.grid_carbon_intensity_gco2_kwh,
      rc.grid_carbon_intensity_gco2_kwh,
      bd.grid_carbon_intensity_gco2_kwh,
      cd.local_grid_gco2_kwh,
    ) ?? 0

  const region = String(
    regionDecision.selected_region_name ||
      regionObj.display_name ||
      rc.grid_zone ||
      bd.grid_zone ||
      cd.grid_zone ||
      cd.compute_location ||
      "—",
  )

  const light =
    numOr(routingImpact.light_chunks, dist.light, Math.round(((numOr(dist.light_pct) || 0) / 100) * (numOr(cd.total_chunks) || 0))) ??
    0
  const medium =
    numOr(routingImpact.medium_chunks, dist.medium, Math.round(((numOr(dist.medium_pct) || 0) / 100) * (numOr(cd.total_chunks) || 0))) ??
    0
  const heavy =
    numOr(routingImpact.heavy_chunks, dist.heavy, Math.round(((numOr(dist.heavy_pct) || 0) / 100) * (numOr(cd.total_chunks) || 0))) ??
    0
  const escalated =
    numOr(
      routingImpact.escalated_chunks,
      asRecord(insights.escalation).chunks_escalated,
      cd.chunks_escalated,
    ) ?? 0
  const totalChunks =
    numOr(cd.total_chunks, routingImpact.total_chunks, dist.total, light + medium + heavy) ?? 0

  const chunksRaw =
    (Array.isArray(cd.chunk_breakdown) && cd.chunk_breakdown) ||
    (Array.isArray(bd.chunk_breakdown) && bd.chunk_breakdown) ||
    []
  const chunkBreakdown = chunksRaw as ChunkBreakdownRow[]

  const sampleRaw = insights.chunk_routing_sample
  const chunkRoutingSample = Array.isArray(sampleRaw)
    ? (sampleRaw as CompactJobMetrics["chunkRoutingSample"])
    : []

  const frontier = resolveFrontierComparison(result as Parameters<typeof resolveFrontierComparison>[0])
  const modelBars = (frontier?.chart_bars || []).map((b) => ({
    model: b.model,
    estimated_gco2e: Number(b.estimated_gco2e) || 0,
    is_ours: Boolean(b.is_ours),
  }))

  const timelineRaw = insights.processing_timeline
  const timeline = Array.isArray(timelineRaw)
    ? (timelineRaw as CompactJobMetrics["timeline"])
    : []

  const tree = insights.document_structure_tree
  const documentTree = Array.isArray(tree) ? tree : null

  return {
    baselineG,
    optimizedG,
    savedG,
    reductionPct,
    emissionsIncreased,
    region,
    intensityGco2Kwh: intensity,
    totalChunks,
    tierMix: { light, medium, heavy, escalated },
    tokens: {
      input: numOr(rc.input_tokens, bd.input_tokens, cd.input_tokens) ?? 0,
      retrieved:
        numOr(rc.retrieved_context_tokens, bd.retrieved_context_tokens, cd.retrieved_context_tokens) ??
        0,
      generated: numOr(rc.generated_tokens, bd.generated_tokens, cd.generated_tokens) ?? 0,
      effective: numOr(rc.effective_tokens, bd.effective_tokens, cd.effective_tokens) ?? 0,
    },
    equation: String(bd.equation || cd.equation || DEFAULT_EQUATION),
    optimizedStages: stageOf(rc.optimized_stages_gco2e || bd.optimized_stages_gco2e),
    baselineStages: stageOf(rc.baseline_stages_gco2e || bd.baseline_stages_gco2e),
    chunkBreakdown,
    chunkRoutingSample,
    modelBars,
    frontier,
    regionDecision: Object.keys(regionDecision).length ? regionDecision : null,
    strategy: Object.keys(strategy).length ? strategy : null,
    documentProfile: Object.keys(profile).length ? profile : null,
    reasonSummary:
      (typeof insights.reason_summary === "string" && insights.reason_summary) ||
      (Array.isArray(strategy.reasons) ? strategy.reasons.slice(0, 3).join(" · ") : null) ||
      null,
    timeline,
    documentTree,
    structureDiagnostics: asRecord(insights.structure_diagnostics),
    selectedModel:
      (typeof insights.selected_model === "string" && insights.selected_model) || null,
    documentType:
      (typeof profile.document_type === "string" && profile.document_type) ||
      (typeof insights.document_type === "string" && insights.document_type) ||
      null,
    complexity: (profile.complexity as string | number | null) ?? null,
    accuracyEstimate: numOr(report.accuracy_estimate, insights.average_confidence) ?? null,
    confidence: numOr(insights.confidence, insights.average_confidence) ?? null,
    schedulingMode:
      (typeof regionDecision.scheduling_mode === "string" &&
        regionDecision.scheduling_mode) ||
      null,
    provider:
      (typeof regionDecision.provider === "string" && regionDecision.provider) ||
      (typeof regionObj.provider === "string" && regionObj.provider) ||
      null,
  }
}
