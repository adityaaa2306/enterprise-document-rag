/**
 * Shared application store for finalized job snapshots.
 *
 * Results publishes. Dashboard / Chat / History subscribe.
 * Sync uses job_id + revision + updated_at — never JS object identity.
 * Cache invalidates on newer job, revision bump, owner change, or explicit clear.
 * Fixed TTLs are intentionally not used.
 */
"use client"

import { apiFetch, getAccessToken } from "@/lib/api"
import {
  extractCompactMetrics,
  type CompactJobMetrics,
} from "@/lib/job-results-metrics"
import { hasDashboardMetrics } from "@/lib/job-result-sync"
import { getLastJobId, rememberJobId } from "@/lib/job-session"
import { peekCurrentUserCache } from "@/lib/current-user-cache"
import { getGuestSessionId } from "@/lib/guest-session"

export type FinalizedJobResult = {
  job_id?: string
  document_id?: string
  filename?: string
  final_summary?: string
  summary_ready?: boolean
  background?: { phase?: string; message?: string } | null
  carbon_data?: Record<string, unknown> | null
  processing_insights?: Record<string, unknown> | null
  comparison_models?: unknown
  our_system?: unknown
  summary_cards?: unknown
  chart_bars?: unknown
  methodology?: string | null
  metrics_ready?: boolean
  search_ready?: boolean
  _revision?: number
  updated_at?: string | number | null
  [key: string]: unknown
}

/** Immutable sync identity for a finalized snapshot. */
export type FinalizedSyncIdentity = {
  jobId: string
  revision: number
  updatedAt: string
  ownerKey: string
}

export type FinalizedMetricsSnapshot = FinalizedSyncIdentity & {
  result: FinalizedJobResult
  /** Single transform — Dashboard Latest Job + Results share these numbers. */
  metrics: CompactJobMetrics
  publishedAt: number
}

const SS_KEY = "ga_finalized_job_v2"

type Listener = (snap: FinalizedMetricsSnapshot | null) => void

let snapshot: FinalizedMetricsSnapshot | null = null
let listeners = new Set<Listener>()
let inflight: Promise<FinalizedMetricsSnapshot | null> | null = null
/** Last jobs-list probe for "is there a newer completed job?" */
let lastNewerJobProbeAt = 0
const NEWER_JOB_PROBE_MS = 12_000

export function currentOwnerKey(): string {
  if (typeof window === "undefined") return "ssr"
  if (getAccessToken()) {
    const u = peekCurrentUserCache()
    if (u?.id != null) return `user:${u.id}`
    return "user:authed"
  }
  const g = getGuestSessionId()
  if (g) return `guest:${g}`
  return "anon"
}

export function revisionOf(result: FinalizedJobResult | null | undefined): number {
  if (!result) return 0
  const r = Number(result._revision)
  return Number.isFinite(r) && r >= 0 ? r : 0
}

export function updatedAtOf(result: FinalizedJobResult | null | undefined): string {
  if (!result) return ""
  const raw =
    result.updated_at ??
    (result.background as { updated_at?: unknown } | null | undefined)?.updated_at ??
    null
  if (raw == null || raw === "") {
    // Stable fallback from carbon richness so serialization still compares.
    const cd = result.carbon_data || {}
    return `r${revisionOf(result)}:b${Number(cd.baseline_cost_gco2e || 0)}:c${Number(cd.total_chunks || 0)}`
  }
  return String(raw)
}

/** Canonical sync key — survives refresh, navigation, and sessionStorage restore. */
export function finalizedSyncKey(
  jobId: string,
  revision: number,
  updatedAt: string,
  ownerKey?: string,
): string {
  const owner = ownerKey ?? currentOwnerKey()
  return `${owner}|${jobId}|rev:${revision}|at:${updatedAt}`
}

export function snapshotSyncKey(snap: FinalizedMetricsSnapshot | null | undefined): string {
  if (!snap) return ""
  return finalizedSyncKey(snap.jobId, snap.revision, snap.updatedAt, snap.ownerKey)
}

/** Field fingerprint for cross-page equality proofs (not object identity). */
export function metricsFieldFingerprint(metrics: CompactJobMetrics | null | undefined): string {
  if (!metrics) return ""
  return [
    metrics.optimizedG.toFixed(6),
    metrics.baselineG.toFixed(6),
    metrics.savedG.toFixed(6),
    metrics.reductionPct.toFixed(4),
    metrics.region,
    metrics.intensityGco2Kwh.toFixed(4),
    metrics.totalChunks,
    metrics.tierMix.light,
    metrics.tierMix.medium,
    metrics.tierMix.heavy,
  ].join("|")
}

function richerThan(
  next: FinalizedJobResult,
  prev: FinalizedJobResult | null | undefined,
): boolean {
  if (!prev) return true
  const nr = revisionOf(next)
  const pr = revisionOf(prev)
  if (nr > pr) return true
  if (nr < pr) return false
  const nAt = updatedAtOf(next)
  const pAt = updatedAtOf(prev)
  if (nAt && pAt && nAt !== pAt) {
    // Prefer lexicographically later ISO timestamps when both look like dates
    if (!Number.isNaN(Date.parse(nAt)) && !Number.isNaN(Date.parse(pAt))) {
      return Date.parse(nAt) >= Date.parse(pAt)
    }
  }
  const nBase = Number(next.carbon_data?.baseline_cost_gco2e || 0)
  const pBase = Number(prev.carbon_data?.baseline_cost_gco2e || 0)
  if (nBase > pBase) return true
  const nChunks = Number(next.carbon_data?.total_chunks || 0)
  const pChunks = Number(prev.carbon_data?.total_chunks || 0)
  return nChunks >= pChunks && hasDashboardMetrics(next)
}

function readSession(): FinalizedMetricsSnapshot | null {
  if (typeof window === "undefined") return null
  try {
    const raw = sessionStorage.getItem(SS_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as FinalizedMetricsSnapshot
    if (!parsed?.jobId || !parsed?.result || !parsed?.metrics) return null
    // Owner mismatch → invalidate (guest→user / logout / login)
    if (parsed.ownerKey && parsed.ownerKey !== currentOwnerKey()) return null
    return parsed
  } catch {
    return null
  }
}

function writeSession(snap: FinalizedMetricsSnapshot | null) {
  if (typeof window === "undefined") return
  try {
    if (!snap) sessionStorage.removeItem(SS_KEY)
    else sessionStorage.setItem(SS_KEY, JSON.stringify(snap))
  } catch {
    /* quota / private mode */
  }
}

function emit() {
  for (const fn of listeners) {
    try {
      fn(snapshot)
    } catch {
      /* ignore */
    }
  }
}

export function peekFinalizedMetrics(): FinalizedMetricsSnapshot | null {
  if (snapshot) {
    if (snapshot.ownerKey !== currentOwnerKey()) {
      clearFinalizedMetrics()
      return null
    }
    return snapshot
  }
  const fromSs = readSession()
  if (fromSs) {
    snapshot = fromSs
    return fromSs
  }
  return null
}

/**
 * Publish finalized job result (Results → store).
 * Updates subscribers only when sync identity changes (job_id / revision / updated_at / owner).
 */
export function publishFinalizedJobResult(
  jobId: string,
  result: FinalizedJobResult,
): FinalizedMetricsSnapshot | null {
  if (!jobId || !result || typeof result !== "object") return peekFinalizedMetrics()
  if (!hasDashboardMetrics(result)) return peekFinalizedMetrics()

  const ownerKey = currentOwnerKey()
  const revision = revisionOf(result)
  const updatedAt = updatedAtOf(result)
  const nextKey = finalizedSyncKey(jobId, revision, updatedAt, ownerKey)

  const prev = peekFinalizedMetrics()
  if (prev && snapshotSyncKey(prev) === nextKey) {
    return prev
  }
  if (prev && prev.jobId === jobId && !richerThan(result, prev.result)) {
    return prev
  }

  const metrics = extractCompactMetrics(
    result as Parameters<typeof extractCompactMetrics>[0],
  )
  snapshot = {
    jobId,
    revision,
    updatedAt,
    ownerKey,
    result,
    metrics,
    publishedAt: Date.now(),
  }
  rememberJobId(jobId)
  writeSession(snapshot)
  emit()
  return snapshot
}

export function clearFinalizedMetrics() {
  snapshot = null
  inflight = null
  lastNewerJobProbeAt = 0
  writeSession(null)
  emit()
}

export function subscribeFinalizedMetrics(fn: Listener): () => void {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}

async function fetchJobResult(jobId: string): Promise<FinalizedJobResult | null> {
  const res = await apiFetch(`/job-result/${jobId}`, { cache: "no-store" })
  if (res.status === 403 || res.status === 404) {
    // Stale id from another Owner / expired guest — drop local pointer.
    try {
      const { clearLastJobId, getLastJobId } = await import("@/lib/job-session")
      if (getLastJobId() === jobId) clearLastJobId()
    } catch {
      /* ignore */
    }
    return null
  }
  if (!res.ok) return null
  const data = (await res.json()) as FinalizedJobResult
  if (data && typeof data === "object" && !data.job_id) data.job_id = jobId
  return data && typeof data === "object" ? data : null
}

async function resolveLatestCompletedJobId(): Promise<string | null> {
  const remembered = getLastJobId()
  try {
    const res = await apiFetch("/jobs?limit=20")
    if (!res.ok) return remembered
    const body = await res.json()
    const jobs = Array.isArray(body?.jobs) ? body.jobs : Array.isArray(body) ? body : []
    for (const j of jobs) {
      const id = String(j?.job_id || j?.id || "")
      const status = String(j?.status || "").toLowerCase()
      if (id && (status === "complete" || status === "completed")) {
        // Prefer newest complete from list; fall back to remembered if list empty of completes
        return id
      }
    }
  } catch {
    /* ignore */
  }
  return remembered
}

/**
 * Ensure latest finalized snapshot is loaded.
 * Cache stays valid until newer job / revision / owner change / force.
 */
export async function ensureFinalizedMetrics(options?: {
  force?: boolean
  jobId?: string | null
}): Promise<FinalizedMetricsSnapshot | null> {
  const force = Boolean(options?.force)
  const preferredId = options?.jobId || null
  const ownerKey = currentOwnerKey()
  const cached = peekFinalizedMetrics()

  if (cached && cached.ownerKey !== ownerKey) {
    clearFinalizedMetrics()
  }

  if (!force && cached && cached.ownerKey === ownerKey) {
    if (preferredId && preferredId !== cached.jobId) {
      // Explicit different job requested
    } else {
      // Probe occasionally for a newer completed job (not a TTL on metrics).
      const now = Date.now()
      if (now - lastNewerJobProbeAt < NEWER_JOB_PROBE_MS) {
        return cached
      }
      lastNewerJobProbeAt = now
      const latestId = preferredId || (await resolveLatestCompletedJobId())
      if (!latestId || latestId === cached.jobId) {
        // Same job — optionally re-fetch only when forced; revision bump comes from Results publish.
        return cached
      }
      // Newer job id discovered — fall through to fetch
    }
  }

  if (inflight && !force) return inflight

  inflight = (async () => {
    try {
      lastNewerJobProbeAt = Date.now()
      const jobId = preferredId || (await resolveLatestCompletedJobId())
      if (!jobId) return peekFinalizedMetrics()

      const existing = peekFinalizedMetrics()
      if (
        !force &&
        existing &&
        existing.jobId === jobId &&
        existing.ownerKey === ownerKey &&
        hasDashboardMetrics(existing.result)
      ) {
        return existing
      }

      const result = await fetchJobResult(jobId)
      if (!result || !hasDashboardMetrics(result)) return peekFinalizedMetrics()
      return publishFinalizedJobResult(jobId, result)
    } finally {
      inflight = null
    }
  })()

  return inflight
}

/**
 * Latest-job chart series from CompactJobMetrics (Layer 1 only).
 * Historical trends must come from the analytics aggregator — not here.
 */
export function chartsFromFinalizedMetrics(
  metrics: CompactJobMetrics,
  label = "Latest job",
): {
  carbonTrend: Array<{
    date: string
    baseline: number
    actual: number
    carbon_saved: number
    efficiency: number
    docs_processed: number
  }>
  energyTrend: Array<{
    date: string
    energy_consumed_kwh: number
    estimated_co2e: number
    docs_processed: number
  }>
  modelBars: CompactJobMetrics["modelBars"]
} {
  const energyKwh =
    metrics.intensityGco2Kwh > 0
      ? metrics.optimizedG / metrics.intensityGco2Kwh
      : 0
  return {
    carbonTrend: [
      {
        date: label,
        baseline: metrics.baselineG,
        actual: metrics.optimizedG,
        carbon_saved: metrics.savedG,
        efficiency: metrics.reductionPct,
        docs_processed: 1,
      },
    ],
    energyTrend: [
      {
        date: label,
        energy_consumed_kwh: energyKwh,
        estimated_co2e: metrics.optimizedG,
        docs_processed: 1,
      },
    ],
    modelBars: metrics.modelBars,
  }
}
