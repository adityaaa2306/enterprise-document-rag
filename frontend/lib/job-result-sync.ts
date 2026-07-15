/**
 * Results-page sync gates — Summary Ready vs Search Ready / metrics ready.
 * Pure helpers so polling cannot stop on a Summary Ready stub.
 */

export type SyncJobStatus = {
  status?: string
  message?: string
  summary_ready?: boolean | null
  background_phase?: string | null
  background_message?: string | null
  metrics_ready?: boolean | null
}

export type SyncJobResult = {
  final_summary?: string
  summary_ready?: boolean
  background?: { phase?: string; message?: string } | null
  carbon_data?: Record<string, unknown> | null
  processing_insights?: unknown
}

export function isSearchReadyPhase(phase: string | null | undefined): boolean {
  const p = (phase || "").toLowerCase()
  return p === "search_ready" || p === "complete" || p === "done"
}

/** Status says background search/metrics finished (not Summary Ready alone). */
export function isSearchReadyFromStatus(data: SyncJobStatus): boolean {
  if (isSearchReadyPhase(data.background_phase)) return true
  const msg = (data.message || "").toLowerCase().trim()
  if (msg === "search ready" || msg.startsWith("search ready")) return true
  if (msg.includes("search available")) return true
  return false
}

/**
 * Polling may stop only when metrics_ready AND search_ready.
 * metrics_ready alone without a search-ready signal is ignored so we don't
 * halt on a raced status flip before the result blob is rewritten.
 */
export function isMetricsReadyFromStatus(data: SyncJobStatus): boolean {
  const searchReady = isSearchReadyFromStatus(data)
  if (data.metrics_ready === true && searchReady) return true
  if (searchReady) return true
  return false
}

/** Dashboard cards need modeled baseline + region — Summary Ready stubs keep baseline at 0. */
export function hasDashboardMetrics(data: SyncJobResult | null | undefined): boolean {
  if (!data) return false
  const cd = (data.carbon_data || {}) as Record<string, unknown>
  const baseline = Number(cd.baseline_cost_gco2e || 0)
  const intensity = Number(cd.local_grid_gco2_kwh || 0)
  const loc = String(cd.compute_location || "").trim().toLowerCase()
  const hasRegion = Boolean(
    cd.region_decision ||
      (cd.grid_zone && String(cd.grid_zone).trim()) ||
      (loc && loc !== "unknown") ||
      intensity > 0,
  )
  return baseline > 0 && hasRegion
}

/**
 * True only when the /job-result payload itself is post-background.
 * Do NOT treat chunks>0 / breakdown presence / phase alone as ready.
 */
export function isMetricsReadyFromResult(data: SyncJobResult | null | undefined): boolean {
  if (!data) return false
  if (!hasDashboardMetrics(data)) return false
  const phase = (data.background?.phase || "").toLowerCase()
  if (isSearchReadyPhase(phase)) return true
  return Number((data.carbon_data as { total_chunks?: number } | undefined)?.total_chunks || 0) > 0
}

/** Fingerprint so richer payloads force React identity / remount of dashboard cards. */
export function resultSyncKey(data: SyncJobResult | null | undefined): string {
  if (!data) return "empty"
  const cd = (data.carbon_data || {}) as Record<string, unknown>
  const rd = cd.region_decision as Record<string, unknown> | undefined
  return [
    data.background?.phase || "",
    Number(cd.baseline_cost_gco2e || 0).toFixed(4),
    Number(cd.actual_cost_gco2e || cd.operational_co2e_g || 0).toFixed(4),
    Number(cd.carbon_saved_grams || 0).toFixed(4),
    String(cd.grid_zone || rd?.selected_region_name || cd.compute_location || ""),
    Number(cd.total_chunks || 0),
    data.processing_insights ? "pi1" : "pi0",
  ].join("|")
}

/** Immutable shallow clone so setState always sees a new object identity. */
export function cloneJobResult<T extends SyncJobResult>(data: T): T {
  return {
    ...data,
    carbon_data: data.carbon_data ? { ...data.carbon_data } : data.carbon_data,
    background: data.background ? { ...data.background } : data.background,
    processing_insights:
      data.processing_insights && typeof data.processing_insights === "object"
        ? { ...(data.processing_insights as Record<string, unknown>) }
        : data.processing_insights,
  } as T
}
