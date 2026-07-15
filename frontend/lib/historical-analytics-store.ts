/**
 * Historical analytics for the current Owner (Layer 2).
 *
 * Aggregates across completed jobs via GET /dashboard-stats.
 * Never recomputes per-job finalized metrics — that is Layer 1's job.
 */
"use client"

import { apiFetch } from "@/lib/api"
import { currentOwnerKey, clearFinalizedMetrics } from "@/lib/finalized-metrics-store"

export type RangeKey = "today" | "7d" | "30d" | "90d" | "custom"

export type TrendPoint = {
  date: string
  date_iso?: string
  savings?: number
  carbon_saved?: number
  baseline?: number
  actual?: number
  efficiency?: number
  docs_processed?: number
}

export type EnergyPoint = {
  date: string
  date_iso?: string
  energy_consumed_kwh?: number
  estimated_co2e?: number
  docs_processed?: number
}

export type HistoricalAnalytics = {
  ownerKey: string
  range: string
  queryKey: string
  total_carbon_saved: number
  total_carbon_consumed: number
  total_baseline_carbon: number
  total_docs: number
  avg_efficiency: number
  carbon_trend: TrendPoint[]
  energy_trend: EnergyPoint[]
  start_date?: string | null
  end_date?: string | null
  point_count?: number
  empty_state_message?: string | null
  fetchedAt: number
}

type Listener = (snap: HistoricalAnalytics | null) => void

let cache: HistoricalAnalytics | null = null
let listeners = new Set<Listener>()
let inflight: Promise<HistoricalAnalytics | null> | null = null

function emit() {
  for (const fn of listeners) {
    try {
      fn(cache)
    } catch {
      /* ignore */
    }
  }
}

export function peekHistoricalAnalytics(): HistoricalAnalytics | null {
  if (!cache) return null
  if (cache.ownerKey !== currentOwnerKey()) {
    clearHistoricalAnalytics()
    return null
  }
  return cache
}

export function clearHistoricalAnalytics() {
  cache = null
  inflight = null
  emit()
}

/** Clear both Layer 1 and Layer 2 on owner change (logout / login / guest flip). */
export function clearOwnerScopedCaches() {
  clearHistoricalAnalytics()
  clearFinalizedMetrics()
}

export function subscribeHistoricalAnalytics(fn: Listener): () => void {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}

function buildQueryKey(
  range: RangeKey,
  customStart?: string,
  customEnd?: string,
): string {
  const owner = currentOwnerKey()
  if (range === "custom") {
    return `${owner}|custom|${customStart || ""}|${customEnd || ""}`
  }
  return `${owner}|${range}`
}

/**
 * Fetch / cache historical analytics for the Owner.
 * Invalidates automatically when ownerKey changes.
 */
export async function ensureHistoricalAnalytics(options: {
  range: RangeKey
  customStart?: string
  customEnd?: string
  force?: boolean
}): Promise<HistoricalAnalytics | null> {
  const ownerKey = currentOwnerKey()
  const queryKey = buildQueryKey(options.range, options.customStart, options.customEnd)
  const existing = peekHistoricalAnalytics()

  if (
    !options.force &&
    existing &&
    existing.ownerKey === ownerKey &&
    existing.queryKey === queryKey
  ) {
    return existing
  }

  if (inflight && !options.force) return inflight

  inflight = (async () => {
    try {
      const params = new URLSearchParams()
      params.set("range", options.range)
      if (options.range === "custom") {
        if (options.customStart) params.set("start_date", options.customStart)
        if (options.customEnd) params.set("end_date", options.customEnd)
      }
      const res = await apiFetch(`/dashboard-stats?${params.toString()}`)
      if (!res.ok) return peekHistoricalAnalytics()
      const data = await res.json()
      cache = {
        ownerKey,
        range: String(data.range || options.range),
        queryKey,
        total_carbon_saved: Number(data.total_carbon_saved || 0),
        total_carbon_consumed: Number(data.total_carbon_consumed || 0),
        total_baseline_carbon: Number(data.total_baseline_carbon || 0),
        total_docs: Number(data.total_docs || 0),
        avg_efficiency: Number(data.avg_efficiency || 0),
        carbon_trend: Array.isArray(data.carbon_trend) ? data.carbon_trend : [],
        energy_trend: Array.isArray(data.energy_trend) ? data.energy_trend : [],
        start_date: data.start_date ?? null,
        end_date: data.end_date ?? null,
        point_count: data.point_count,
        empty_state_message: data.empty_state_message ?? null,
        fetchedAt: Date.now(),
      }
      emit()
      return cache
    } catch {
      return peekHistoricalAnalytics()
    } finally {
      inflight = null
    }
  })()

  return inflight
}
