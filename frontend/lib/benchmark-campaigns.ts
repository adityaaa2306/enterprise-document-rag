/**
 * Read-only client for offline benchmark campaign artifacts.
 * Loads static JSON from /benchmark-campaigns — never calls LLMs.
 */
import type {
  BenchmarkWorkload,
  CampaignBundle,
  CampaignConfig,
  CampaignIndexEntry,
  CampaignMetadata,
  DashboardPayload,
  QuestionExplorerItem,
} from "@/lib/benchmark-types"

const BASE = "/benchmark-campaigns"

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { cache: "no-store" })
  if (!res.ok) {
    throw new Error(`Failed to load ${url} (${res.status})`)
  }
  return (await res.json()) as T
}

export function isSuccessfulCampaign(entry: CampaignIndexEntry): boolean {
  if ((entry.status || "").toLowerCase() === "failed") return false
  if (entry.dry_run) return true
  // Live campaigns with zero spend / zero runtime are treated as unsuccessful defaults
  if ((entry.total_api_cost_usd || 0) <= 0 && (entry.total_runtime_sec || 0) < 1) {
    return false
  }
  return true
}

export function campaignWorkload(
  entry: CampaignIndexEntry | CampaignBundle | null | undefined,
): BenchmarkWorkload {
  if (!entry) return "interactive_rag"
  const raw =
    "workload" in entry && entry.workload
      ? entry.workload
      : "config" in entry
        ? entry.config?.workload ||
          entry.metadata?.workload ||
          entry.dashboard?.workload
        : undefined
  const w = String(raw || "").toLowerCase()
  if (w === "document_summarization") return "document_summarization"
  const suite = String(
    "suite" in entry
      ? entry.suite
      : "config" in entry
        ? entry.config?.suite || entry.metadata?.suite
        : "",
  ).toLowerCase()
  if (suite.startsWith("summarization") || suite.startsWith("summarize")) {
    return "document_summarization"
  }
  return "interactive_rag"
}

export function filterCampaignsByWorkload(
  rows: CampaignIndexEntry[],
  workload: BenchmarkWorkload,
): CampaignIndexEntry[] {
  return rows.filter((r) => campaignWorkload(r) === workload)
}

/** Most recent successful campaign; never returns a failed campaign as default. */
export function pickDefaultCampaign(
  rows: CampaignIndexEntry[],
  workload?: BenchmarkWorkload,
): CampaignIndexEntry | null {
  const pool = workload ? filterCampaignsByWorkload(rows, workload) : rows
  const sorted = [...pool].sort((a, b) => {
    const ta = Date.parse(a.timestamp_utc || "") || 0
    const tb = Date.parse(b.timestamp_utc || "") || 0
    return tb - ta
  })
  return sorted.find(isSuccessfulCampaign) || null
}

/**
 * Pair a successful RAG campaign with a summarization campaign.
 * Prefer matching document_id so cost/CO₂e comparison is on the same corpus.
 */
export function pickCrossWorkloadPair(rows: CampaignIndexEntry[]): {
  rag: CampaignIndexEntry | null
  summarization: CampaignIndexEntry | null
} {
  const byRecency = (a: CampaignIndexEntry, b: CampaignIndexEntry) =>
    (Date.parse(b.timestamp_utc || "") || 0) -
    (Date.parse(a.timestamp_utc || "") || 0)

  const ragPool = filterCampaignsByWorkload(rows, "interactive_rag")
    .filter(isSuccessfulCampaign)
    .sort(byRecency)
  const sumPool = filterCampaignsByWorkload(rows, "document_summarization")
    .filter(isSuccessfulCampaign)
    .sort(byRecency)

  for (const rag of ragPool) {
    if (!rag.document_id) continue
    const match = sumPool.find((s) => s.document_id === rag.document_id)
    if (match) return { rag, summarization: match }
  }

  return {
    rag: ragPool[0] || null,
    summarization: sumPool[0] || null,
  }
}

/** Campaign-level total CO₂e (g): prefer exported totals, else avg × successful runs. */
export function totalEstimatedCo2eG(bundle: CampaignBundle): number {
  const rows = bundle.dashboard?.table?.per_model || []
  return rows.reduce((acc, r) => {
    if (r.total_estimated_co2e_g != null) {
      return acc + Number(r.total_estimated_co2e_g)
    }
    const n = Math.max(1, Number(r.n_ok || r.n_runs || 1))
    return acc + Number(r.avg_estimated_co2e_g || 0) * n
  }, 0)
}

/** Campaign-level total estimated API cost (USD). */
export function totalEstimatedCostUsd(bundle: CampaignBundle): number {
  const totals = bundle.dashboard?.totals
  if (totals?.total_api_cost_usd != null) {
    return Number(totals.total_api_cost_usd)
  }
  if (bundle.metadata?.total_api_cost_usd != null) {
    return Number(bundle.metadata.total_api_cost_usd)
  }
  const rows = bundle.dashboard?.table?.per_model || []
  return rows.reduce(
    (acc, r) => acc + Number(r.total_estimated_api_cost_usd || 0),
    0,
  )
}

/** Per-model total CO₂e (g). */
export function modelTotalCo2eG(row: {
  total_estimated_co2e_g?: number | null
  avg_estimated_co2e_g?: number | null
  n_ok?: number
  n_runs?: number
}): number {
  if (row.total_estimated_co2e_g != null) {
    return Number(row.total_estimated_co2e_g)
  }
  const n = Math.max(1, Number(row.n_ok || row.n_runs || 1))
  return Number(row.avg_estimated_co2e_g || 0) * n
}

export async function listBenchmarkCampaigns(): Promise<CampaignIndexEntry[]> {
  const rows = await fetchJson<CampaignIndexEntry[]>(`${BASE}/index.json`)
  return [...rows].sort((a, b) => {
    const ta = Date.parse(a.timestamp_utc || "") || 0
    const tb = Date.parse(b.timestamp_utc || "") || 0
    return tb - ta
  })
}

export async function loadCampaignBundle(
  campaignId: string,
  indexHint?: CampaignIndexEntry,
): Promise<CampaignBundle> {
  const base = `${BASE}/${encodeURIComponent(campaignId)}`
  const [config, metadata, dashboard, summary, questionsWrap] = await Promise.all([
    fetchJson<CampaignConfig>(`${base}/config.json`),
    fetchJson<CampaignMetadata>(`${base}/metadata.json`),
    fetchJson<DashboardPayload>(`${base}/dashboard.json`),
    fetchJson<Record<string, unknown>>(`${base}/summary.json`),
    fetchJson<{
      questions: QuestionExplorerItem[]
      workload?: string
    }>(`${base}/questions.json`),
  ])

  const workload =
    metadata.workload ||
    config.workload ||
    dashboard.workload ||
    questionsWrap.workload ||
    "interactive_rag"

  const index: CampaignIndexEntry =
    indexHint ||
    ({
      campaign_id: campaignId,
      label: campaignId,
      benchmark_version: metadata.benchmark_version,
      workload,
      suite: metadata.suite,
      document_id: metadata.document_id,
      document_name: config.filename || null,
      timestamp_utc: metadata.timestamp_utc,
      models: metadata.models,
      dry_run: metadata.dry_run,
      total_api_cost_usd: metadata.total_api_cost_usd,
      total_runtime_sec: metadata.total_runtime_sec,
    } satisfies CampaignIndexEntry)

  return {
    index,
    config,
    metadata,
    dashboard,
    summary,
    questions: questionsWrap.questions || [],
  }
}

export function fmtNum(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(Number(value))) return "—"
  return Number(value).toFixed(digits)
}

export function fmtUsd(value: number | null | undefined, digits = 4): string {
  if (value == null || Number.isNaN(Number(value))) return "—"
  return `$${Number(value).toFixed(digits)}`
}

export function fmtMs(value: number | null | undefined): string {
  if (value == null || Number.isNaN(Number(value))) return "—"
  return `${Math.round(Number(value)).toLocaleString()} ms`
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

export function shortHash(hash: string | null | undefined, n = 12): string {
  if (!hash) return "—"
  return hash.slice(0, n)
}

/** Human-readable participant label for charts / tables. */
export function displayParticipantName(model: string | null | undefined): string {
  if (!model) return "—"
  const key = model.trim().toLowerCase().replace(/_/g, "-")
  if (
    key === "intelligent-router" ||
    key === "intelligent router" ||
    key === "system-router" ||
    key === "router"
  ) {
    return "Intelligent Router"
  }
  return model.replace(/^gpt-/, "")
}
