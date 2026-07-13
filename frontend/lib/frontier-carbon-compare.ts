/**
 * Rebuild frontier model comparison from workflow carbon_data.
 * Keeps the results UI aligned with energy × Electricity Maps accounting
 * even if a cached/old API payload still embeds legacy chunk×grams bars.
 */

export const FRONTIER_RELATIVE_INTENSITY: ReadonlyArray<readonly [string, number]> = [
  ["GPT-o3", 2.2],
  ["GPT-4", 1.9],
  ["Llama 4 Behemoth", 2.0],
  ["Claude 4 Opus", 1.7],
  ["GPT-4o", 1.4],
  ["Gemini 2.5 Pro", 1.35],
  ["Llama 4 Maverick", 1.05],
  ["Gemma 3", 0.9],
] as const

export const OUR_SYSTEM_NAME = "Green Agentic Document Processing System"
export const OUR_SYSTEM_TAGLINE = "Smart Carbon-Aware Routing"

const LEGACY_CHUNK_GRAMS = 5.25
const LEGACY_BASELINE_GUARD = 150

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

export type CarbonLike = {
  baseline_cost_gco2e?: number
  actual_cost_gco2e?: number
  carbon_saved_grams?: number
  efficiency_percent?: number
  total_chunks?: number
  baseline_energy_kwh?: number
  actual_energy_kwh?: number
  local_grid_gco2_kwh?: number
  methodology?: string | null
  breakdown?: {
    baseline_co2e_g?: number
    actual_co2e_g?: number
    baseline_energy_kwh?: number
    optimized_energy_kwh?: number
    grid_carbon_intensity_gco2_kwh?: number
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
  }
  badges: string[]
  chart_bars: Array<{ model: string; estimated_gco2e: number; is_ours: boolean }>
  methodology: string
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

  // Replace legacy chunk×grams baselines (e.g. 48 × 5.25 = 252).
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

  let saved = num(carbon.carbon_saved_grams)
  if (saved <= 0 && baseline > 0) saved = Math.max(0, baseline - actual)
  let efficiency = num(carbon.efficiency_percent)
  if (efficiency <= 0 && baseline > 0) {
    efficiency = Math.min(100, (saved / baseline) * 100)
  }

  const comparison_models: ComparisonModelRow[] = FRONTIER_RELATIVE_INTENSITY.map(
    ([model, factor]) => {
      const estimated = baseline * factor
      const savedG = estimated - actual
      const reduction = estimated > 0 ? (savedG / estimated) * 100 : 0
      return {
        model,
        relative_factor: factor,
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
    },
    badges,
    chart_bars,
    methodology:
      carbon.methodology ||
      "Frontier estimates = document baseline energy × relative model intensity × live Electricity Maps grid intensity. Our system uses measured workflow energy × the same intensity.",
  }
}

/** Always rebuild from carbon_data so the UI cannot show stale 252g bars. */
export function resolveFrontierComparison(result: {
  carbon_data?: CarbonLike | null
  comparison_models?: ComparisonModelRow[] | null
  our_system?: { name: string; tagline?: string | null; carbon: number } | null
  summary_cards?: FrontierComparisonPayload["summary_cards"] | null
  badges?: string[] | null
  chart_bars?: FrontierComparisonPayload["chart_bars"] | null
  methodology?: string | null
}): FrontierComparisonPayload | null {
  const rebuilt = buildFrontierComparisonFromCarbon(result.carbon_data)
  if (rebuilt) return rebuilt

  if (
    result.comparison_models?.length &&
    result.our_system &&
    result.summary_cards
  ) {
    return {
      comparison_models: result.comparison_models.map((m) => ({
        model: m.model,
        relative_factor: num(m.relative_factor, 1),
        estimated_gco2e: num(m.estimated_gco2e),
        saved_gco2e: num(m.saved_gco2e),
        reduction_percent: num(m.reduction_percent),
      })),
      our_system: {
        name: result.our_system.name,
        tagline: result.our_system.tagline || OUR_SYSTEM_TAGLINE,
        carbon: num(result.our_system.carbon),
      },
      summary_cards: result.summary_cards,
      badges: result.badges || [],
      chart_bars: result.chart_bars || [],
      methodology:
        result.methodology ||
        result.carbon_data?.methodology ||
        "",
    }
  }
  return null
}
