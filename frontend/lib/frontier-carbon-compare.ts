/**
 * Rebuild frontier model comparison from workflow carbon_data.
 *
 * Each frontier bar = entire workflow (map+compile token mass + shared stages)
 * served by that single model. Our system = per-chunk routed estimate.
 */

import { A_J_PER_TOKEN_MEDIUM } from "./carbon-constants"

export const FRONTIER_MODEL_J_PER_TOKEN: ReadonlyArray<readonly [string, number]> = [
  ["GPT-o3", 7.5],
  ["GPT-4", 6.5],
  ["Llama 4 Behemoth", 6.5],
  ["Claude 4 Opus", 6.0],
  ["GPT-4o", 4.0],
  ["Gemini 2.5 Pro", 3.8],
  ["Llama 4 Maverick", 2.8],
  ["Gemma 3", 1.6],
] as const

/** @deprecated factor alias vs medium J — prefer FRONTIER_MODEL_J_PER_TOKEN */
export const FRONTIER_RELATIVE_INTENSITY: ReadonlyArray<readonly [string, number]> =
  FRONTIER_MODEL_J_PER_TOKEN.map(
    ([name, j]) => [name, Math.round((j / A_J_PER_TOKEN_MEDIUM) * 10000) / 10000] as const,
  )

export const OUR_SYSTEM_NAME = "Green Agentic Document Processing System"
export const OUR_SYSTEM_TAGLINE = "Smart Carbon-Aware Routing"

const LEGACY_CHUNK_GRAMS = 5.25
const LEGACY_BASELINE_GUARD = 150
const JOULES_PER_KWH = 3_600_000
const HEAVY_J = 6.5

function num(value: unknown, fallback = 0): number {
  const n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

function round1(value: number): number {
  return Math.round(value * 10) / 10
}

function round4(value: number): number {
  return Math.round(value * 10000) / 10000
}

export type ChunkBreakdownRow = {
  chunk_index?: number
  tier?: string
  model?: string
  input_tokens?: number
  map_tokens?: number
  energy_kwh?: number
  co2e_g?: number
  j_per_token?: number
}

export type CarbonLike = {
  baseline_cost_gco2e?: number
  actual_cost_gco2e?: number
  carbon_saved_grams?: number
  efficiency_percent?: number
  emissions_direction?: string
  total_chunks?: number
  baseline_energy_kwh?: number
  actual_energy_kwh?: number
  local_grid_gco2_kwh?: number
  input_tokens?: number
  methodology?: string | null
  chunk_breakdown?: ChunkBreakdownRow[] | null
  breakdown?: {
    baseline_co2e_g?: number
    actual_co2e_g?: number
    baseline_energy_kwh?: number
    optimized_energy_kwh?: number
    grid_carbon_intensity_gco2_kwh?: number
    input_tokens?: number
    compile_tokens?: number
    map_tokens_total?: number
    map_tokens_by_tier?: Record<string, number>
    baseline_stages_gco2e?: Record<string, number>
    chunk_breakdown?: ChunkBreakdownRow[]
    emissions_direction?: string
    carbon_saved_g?: number
    reduction_percent?: number
    [key: string]: unknown
  } | null
}

export type ComparisonModelRow = {
  model: string
  relative_factor: number
  estimated_gco2e: number
  saved_gco2e: number
  reduction_percent: number
}

export type FrontierComparisonPayload = {
  comparison_models: ComparisonModelRow[]
  our_system: { name: string; tagline: string; carbon: number }
  summary_cards: {
    actual_emissions_gco2e: number
    carbon_saved_gco2e: number
    reduction_percent: number
    heavy_model_baseline_gco2e: number
    estimated_optimized_pipeline_emissions_g?: number
    estimated_baseline_pipeline_emissions_g?: number
    emissions_direction?: string
  }
  badges: string[]
  chart_bars: Array<{ model: string; estimated_gco2e: number; is_ours: boolean }>
  methodology: string
  chunk_breakdown?: ChunkBreakdownRow[]
}

function resolveBaseline(carbon: CarbonLike): number {
  const bd = carbon.breakdown || {}
  let baseline = num(carbon.baseline_cost_gco2e)
  if (baseline <= 0) baseline = num(bd.baseline_co2e_g)

  const energy =
    num(carbon.baseline_energy_kwh) || num(bd.baseline_energy_kwh)
  const intensity =
    num(carbon.local_grid_gco2_kwh) ||
    num(bd.grid_carbon_intensity_gco2_kwh)

  if (baseline > LEGACY_BASELINE_GUARD && energy > 0 && intensity > 0) {
    const rebuilt = energy * intensity
    if (rebuilt > 0 && rebuilt < baseline) baseline = rebuilt
  }

  if (baseline <= 0 && energy > 0 && intensity > 0) {
    baseline = energy * intensity
  }

  const chunks = num(carbon.total_chunks)
  if (
    baseline > LEGACY_BASELINE_GUARD &&
    chunks > 0 &&
    Math.abs(baseline - chunks * LEGACY_CHUNK_GRAMS) < 0.5
  ) {
    if (energy > 0 && intensity > 0) baseline = energy * intensity
  }

  return baseline
}

function workflowInferenceTokens(carbon: CarbonLike): number {
  const bd = carbon.breakdown || {}
  let mapTotal = num(bd.map_tokens_total)
  if (mapTotal <= 0 && bd.map_tokens_by_tier) {
    mapTotal = Object.values(bd.map_tokens_by_tier).reduce((s, v) => s + num(v), 0)
  }
  const compileTok = num(bd.compile_tokens)
  if (mapTotal + compileTok > 0) return mapTotal + compileTok
  const inp = num(bd.input_tokens || carbon.input_tokens)
  if (inp > 0) return Math.max(Math.floor(inp * 1.25), inp) + Math.floor(inp / 3)
  return 0
}

function estimateFrontierG(
  carbon: CarbonLike,
  baseline: number,
  modelJ: number,
): number {
  const bd = carbon.breakdown || {}
  const intensity =
    num(carbon.local_grid_gco2_kwh) ||
    num(bd.grid_carbon_intensity_gco2_kwh) ||
    700.0
  const tokens = workflowInferenceTokens(carbon)

  // Absolute estimate when baseline is missing (Summary Ready before full carbon).
  if (baseline <= 0) {
    if (tokens > 0 && intensity > 0) {
      return Math.max(0, ((tokens * modelJ) / JOULES_PER_KWH) * intensity)
    }
    return 0
  }

  const stages = (bd.baseline_stages_gco2e || {}) as Record<string, number>
  let inferenceG = num(stages.inference_gco2e)
  let otherG = 0
  for (const [k, v] of Object.entries(stages)) {
    if (k === "inference_gco2e" || k === "total_gco2e" || k === "infrastructure_gco2e") continue
    otherG += num(v)
  }
  let infraG = num(stages.infrastructure_gco2e)
  if (inferenceG <= 0) {
    inferenceG = baseline * 0.86
    otherG = baseline * 0.05
    infraG = Math.max(0, baseline - inferenceG - otherG)
  }

  let newInferenceG: number
  if (tokens > 0) {
    // IT-only (no PUE) — infrastructure share is rescaled below (matches backend).
    const itJ = tokens * modelJ
    newInferenceG = (itJ / JOULES_PER_KWH) * intensity
  } else {
    newInferenceG = inferenceG * (modelJ / HEAVY_J)
  }

  const itOld = otherG + inferenceG
  const itNew = otherG + newInferenceG
  const infraNew = itOld > 0 ? infraG * (itNew / itOld) : infraG
  return Math.max(0, itNew + infraNew)
}

export function looksLikeLegacyComparison(
  models: Array<{ estimated_gco2e?: number }> | null | undefined,
  carbon?: CarbonLike | null,
): boolean {
  if (!models?.length) return true
  const maxEst = Math.max(...models.map((m) => num(m.estimated_gco2e)))
  if (maxEst >= LEGACY_BASELINE_GUARD) return true
  const chunks = num(carbon?.total_chunks)
  if (chunks > 0 && Math.abs(maxEst - chunks * LEGACY_CHUNK_GRAMS) < 1) {
    return true
  }
  return false
}

export function buildFrontierComparisonFromCarbon(
  carbon: CarbonLike | null | undefined,
): FrontierComparisonPayload | null {
  if (!carbon) return null

  const baseline = resolveBaseline(carbon)
  const bd = carbon.breakdown || {}
  let actual = num(carbon.actual_cost_gco2e)
  if (actual <= 0) actual = num(bd.actual_co2e_g)
  if (actual <= 0) {
    const actEnergy =
      num(carbon.actual_energy_kwh) || num(bd.optimized_energy_kwh)
    const intensity =
      num(carbon.local_grid_gco2_kwh) ||
      num(bd.grid_carbon_intensity_gco2_kwh)
    if (actEnergy > 0 && intensity > 0) actual = actEnergy * intensity
  }

  if (baseline <= 0 && actual <= 0) return null

  // Signed savings — do not clamp to zero
  let saved: number
  if (carbon.carbon_saved_grams != null || bd.carbon_saved_g != null) {
    saved = num(carbon.carbon_saved_grams ?? bd.carbon_saved_g)
  } else {
    saved = baseline - actual
  }
  let efficiency: number
  if (carbon.efficiency_percent != null || bd.reduction_percent != null) {
    efficiency = num(carbon.efficiency_percent ?? bd.reduction_percent)
  } else {
    efficiency = baseline > 0 ? (saved / baseline) * 100 : 0
  }

  const comparison_models: ComparisonModelRow[] = FRONTIER_MODEL_J_PER_TOKEN.map(
    ([model, modelJ]) => {
      const estimated = estimateFrontierG(carbon, baseline, modelJ)
      const savedG = estimated - actual
      const reduction = estimated > 0 ? (savedG / estimated) * 100 : 0
      return {
        model,
        relative_factor: Math.round((modelJ / A_J_PER_TOKEN_MEDIUM) * 10000) / 10000,
        estimated_gco2e: round1(estimated),
        saved_gco2e: round1(savedG),
        reduction_percent: round1(reduction),
      }
    },
  )

  const badges: string[] = []
  const seen = new Set<number>()
  ;[...comparison_models]
    .sort(
      (a, b) =>
        b.reduction_percent - a.reduction_percent ||
        b.saved_gco2e - a.saved_gco2e,
    )
    .forEach((row) => {
      if (badges.length >= 3) return
      if (seen.has(row.relative_factor)) return
      const pct = Math.round(row.reduction_percent)
      if (pct <= 0) return
      seen.add(row.relative_factor)
      badges.push(`${pct}% less CO₂ than ${row.model}`)
    })

  const chart_bars = [
    ...comparison_models.map((row) => ({
      model: row.model,
      estimated_gco2e: row.estimated_gco2e,
      is_ours: false,
    })),
    {
      model: OUR_SYSTEM_NAME,
      estimated_gco2e: round1(actual),
      is_ours: true,
    },
  ].sort((a, b) => b.estimated_gco2e - a.estimated_gco2e)

  const chunk_breakdown =
    carbon.chunk_breakdown || bd.chunk_breakdown || []

  return {
    comparison_models,
    our_system: {
      name: OUR_SYSTEM_NAME,
      tagline: OUR_SYSTEM_TAGLINE,
      carbon: round1(actual),
    },
    summary_cards: {
      actual_emissions_gco2e: round4(actual),
      carbon_saved_gco2e: round4(saved),
      reduction_percent: round1(efficiency),
      heavy_model_baseline_gco2e: round4(baseline),
      estimated_optimized_pipeline_emissions_g: round4(actual),
      estimated_baseline_pipeline_emissions_g: round4(baseline),
      emissions_direction:
        carbon.emissions_direction || bd.emissions_direction || undefined,
    },
    badges,
    chart_bars,
    chunk_breakdown,
    methodology:
      carbon.methodology ||
      "Each frontier bar = entire document workflow on that single model. Our system = per-chunk Light/Medium/Heavy routing. Baseline = naive all-heavy frontier.",
  }
}

/** Always rebuild from carbon_data so the UI cannot show stale 252g bars. */
export function resolveFrontierComparison(
  result:
    | {
        carbon_data?: CarbonLike | null
        comparison_models?: ComparisonModelRow[] | null
        our_system?: { name: string; tagline?: string; carbon: number } | null
        summary_cards?: FrontierComparisonPayload["summary_cards"] | null
        badges?: string[] | null
        chart_bars?: FrontierComparisonPayload["chart_bars"] | null
        methodology?: string | null
      }
    | null
    | undefined,
): FrontierComparisonPayload | null {
  if (!result) return null
  const rebuilt = buildFrontierComparisonFromCarbon(result.carbon_data)
  if (rebuilt) return rebuilt
  if (!result.comparison_models?.length) return null
  return {
    comparison_models: result.comparison_models,
    our_system: {
      name: result.our_system?.name || OUR_SYSTEM_NAME,
      tagline: result.our_system?.tagline || OUR_SYSTEM_TAGLINE,
      carbon: num(result.our_system?.carbon),
    },
    summary_cards: result.summary_cards || {
      actual_emissions_gco2e: 0,
      carbon_saved_gco2e: 0,
      reduction_percent: 0,
      heavy_model_baseline_gco2e: 0,
    },
    badges: result.badges || [],
    chart_bars: result.chart_bars || [],
    methodology: result.methodology || "",
  }
}
