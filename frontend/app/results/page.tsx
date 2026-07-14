"use client"

import { motion } from "framer-motion"
import { useState, useEffect, Suspense, useCallback } from "react"
import { useSearchParams, useRouter } from "next/navigation"
import { Sidebar } from "@/components/sidebar"
import { TopBar } from "@/components/top-bar"
import { LiveFeed } from "@/components/live-feed"
import { JobQueuePanel } from "@/components/job-queue-panel"
import { ExecutionRegionPanel } from "@/components/execution-region-panel"
import { Card } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Leaf, Zap, Star, Copy, Download, Info } from "lucide-react"
import { Button } from "@/components/ui/button"
import { apiFetch } from "@/lib/api"
import { getLastJobId, rememberJobId } from "@/lib/job-session"
import {
  ProcessingInsightsPanel,
  type ProcessingInsightsData,
} from "@/components/processing-insights"
import { AdaptivePipelinePanel } from "@/components/adaptive-pipeline-panel"
import { DocumentStructureViewer } from "@/components/document-structure-viewer"
import { PipelineIntelligencePanel } from "@/components/pipeline-intelligence-panel"
import {
  CarbonComparisonDashboard,
  type ComparisonModelRow,
  type OurSystemCarbon,
  type CarbonSummaryCards,
  type ChartBarRow,
  type CarbonBreakdown,
} from "@/components/carbon-comparison-dashboard"
import { MarkdownContent } from "@/components/markdown-content"
import { AnswerSources, type RetrievedChunkMeta } from "@/components/answer-sources"
import { AnswerMetaFooter } from "@/components/answer-meta-footer"
import { DeveloperDetails } from "@/components/developer-details"
import { unwrapOuterMarkdownFence } from "@/lib/utils"
import { resolveFrontierComparison } from "@/lib/frontier-carbon-compare"

/** Canonical Boundary A copy — never show legacy ChatGPT-class chunk×grams text. */
const BOUNDARY_A_ASSUMPTIONS =
  "This system estimates operational carbon emissions using:\n" +
  "• Energy-per-token estimates (literature-aligned J/token by model tier)\n" +
  "• Live regional electricity carbon intensity (Electricity Maps)\n" +
  "• Datacenter Power Usage Effectiveness (PUE)\n\n" +
  "Excluded:\n" +
  "• Model training emissions\n" +
  "• Hardware manufacturing\n" +
  "• End-of-life lifecycle emissions\n\n" +
  "Reporting boundary: A_operational (Operational Emissions — Boundary A)."

function pickAssumptionsText(...candidates: Array<string | null | undefined>): string {
  for (const raw of candidates) {
    const text = (raw || "").trim()
    if (!text) continue
    if (/chatgpt-class|4\.32\s*g|15\s*mg|chunk count\s*×/i.test(text)) continue
    return text
  }
  return BOUNDARY_A_ASSUMPTIONS
}

/** Poll every 1.5s; skip ticks while a request is in flight (avoids stampede). */
const POLL_INTERVAL_MS = 1500
/** Stop polling after this wall-clock budget so the UI never spins forever. */
const POLL_TIMEOUT_MS = Number(
  process.env.NEXT_PUBLIC_JOB_POLL_TIMEOUT_MS || 45 * 60 * 1000,
)

const TERMINAL_STATUSES = new Set([
  "complete",
  "completed",
  "done",
  "success",
  "error",
  "failed",
  "failure",
  "cancelled",
  "canceled",
])

function normalizeStatus(raw: string | undefined | null): string {
  return (raw || "").trim().toLowerCase()
}

function isTerminalStatus(raw: string | undefined | null): boolean {
  return TERMINAL_STATUSES.has(normalizeStatus(raw))
}

function isSuccessStatus(raw: string | undefined | null): boolean {
  const s = normalizeStatus(raw)
  return s === "complete" || s === "completed" || s === "done" || s === "success"
}

function isErrorStatus(raw: string | undefined | null): boolean {
  const s = normalizeStatus(raw)
  return s === "error" || s === "failed" || s === "failure" || s === "cancelled" || s === "canceled"
}

interface JobStatus {
  status: string
  progress: number
  message: string
  stage?: string | null
  chunks_done?: number | null
  chunks_total?: number | null
  partial?: Record<string, unknown> | null
}

interface CarbonData {
  carbon_saved_grams: number
  baseline_cost_gco2e: number
  actual_cost_gco2e: number
  efficiency_percent: number
  total_chunks: number
  chunks_escalated: number
  compute_location: string
  local_grid_gco2_kwh: number
  message: string
  baseline_energy_kwh?: number
  actual_energy_kwh?: number
  grid_zone?: string | null
  grid_datetime?: string | null
  breakdown?: CarbonBreakdown | Record<string, unknown> | null
  methodology?: string | null
  assumptions_panel?: string | null
  reporting_boundary_label?: string | null
  estimated_baseline_pipeline_emissions_g?: number
  estimated_optimized_pipeline_emissions_g?: number
  input_tokens?: number
  retrieved_context_tokens?: number
  generated_tokens?: number
  effective_tokens?: number
  grid_updated_at?: string | null
  report_card?: Record<string, unknown> | null
  routing_impact?: Record<string, number | string> | null
  uncertainty?: {
    enabled?: boolean
    optimized?: {
      low_gco2e?: number
      typical_gco2e?: number
      high_gco2e?: number
    }
  } | null
  pue?: number
  region_decision?: {
    selected_region_name?: string
    selected_region_id?: string
    selected_region?: {
      display_name?: string
      id?: string
      grid_zone?: string
      provider?: string
    } | null
    provider?: string
    grid_carbon_intensity_gco2_kwh?: number
    grid_zone?: string
    scheduling_mode?: string
    data_source?: string
    data_freshness?: string
    confidence?: string
    execution_status?: string
    future_support?: string
    reason?: string
    timestamp?: string
  } | null
}

function asBreakdown(raw: unknown): Record<string, unknown> {
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

interface JobResult {
  job_id: string
  document_id: string
  filename: string
  final_summary: string
  carbon_data: CarbonData
  processing_insights?: ProcessingInsightsData | null
  comparison_models?: ComparisonModelRow[] | null
  our_system?: OurSystemCarbon | null
  summary_cards?: CarbonSummaryCards | null
  badges?: string[] | null
  chart_bars?: ChartBarRow[] | null
  methodology?: string | null
}

interface ChatMessage {
  role: "user" | "assistant"
  content: string
  meta?: {
    confidence?: number | null
    reasoning_path?: string[] | null
    model_used?: string | null
    entities_used?: string[] | null
    missing_context?: string[] | null
    sources?: string[]
    retrieved_chunks?: RetrievedChunkMeta[] | null
    knowledge_sources?: string[] | null
    skill?: string | null
    latency_ms?: number | null
  }
}

function formatPreferenceLabel(pref?: string | null) {
  if (!pref) return "Smart Routing"
  return pref
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

function ResultsContent() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const urlJobId = searchParams.get("job_id")
  const [jobId, setJobId] = useState<string | null>(urlJobId)

  const [isComplete, setIsComplete] = useState(false)
  const [jobFailed, setJobFailed] = useState(false)
  const [pollTimedOut, setPollTimedOut] = useState(false)
  const [failureMessage, setFailureMessage] = useState<string | null>(null)
  const [logs, setLogs] = useState<any[]>([])
  const [liveProgress, setLiveProgress] = useState(0)
  const [liveStage, setLiveStage] = useState<string | null>(null)
  const [chunkProgress, setChunkProgress] = useState<string | null>(null)
  const [result, setResult] = useState<JobResult | null>(null)
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [chatInput, setChatInput] = useState("")
  const [isChatLoading, setIsChatLoading] = useState(false)

  // Restore last job when visiting /results without query (sidebar nav)
  useEffect(() => {
    if (urlJobId) {
      setJobId(urlJobId)
      rememberJobId(urlJobId)
      return
    }
    const last = getLastJobId()
    if (last) {
      setJobId(last)
      router.replace(`/results?job_id=${last}`)
    }
  }, [urlJobId, router])

  const selectJob = useCallback(
    (id: string) => {
      rememberJobId(id)
      setJobId(id)
      setIsComplete(false)
      setJobFailed(false)
      setPollTimedOut(false)
      setFailureMessage(null)
      setLogs([])
      setResult(null)
      setLiveProgress(0)
      setLiveStage(null)
      setChunkProgress(null)
      setChatMessages([])
      router.replace(`/results?job_id=${id}`)
    },
    [router],
  )

  useEffect(() => {
    if (!jobId) return
    rememberJobId(jobId)

    let cancelled = false
    let pollInterval: ReturnType<typeof setInterval> | undefined
    let inFlight = false
    const startedAt = Date.now()

    const stopPolling = () => {
      if (pollInterval !== undefined) {
        clearInterval(pollInterval)
        pollInterval = undefined
      }
    }

    const appendLog = (message: string, type: "info" | "error" = "info") => {
      if (cancelled) return
      setLogs((prev) => {
        const newLog = {
          id: `${Date.now()}-${prev.length}`,
          timestamp: new Date().toLocaleTimeString(),
          message,
          type,
        }
        if (prev.length > 0 && prev[prev.length - 1].message === message) return prev
        return [...prev, newLog]
      })
    }

    const pollStatus = async () => {
      if (cancelled || inFlight) return
      inFlight = true

      if (Date.now() - startedAt > POLL_TIMEOUT_MS) {
        stopPolling()
        inFlight = false
        if (!cancelled) {
          setPollTimedOut(true)
          setFailureMessage(
            `Polling timed out after ${Math.round(POLL_TIMEOUT_MS / 60000)} minutes. The job may still be running on the server — refresh later or check worker logs.`,
          )
          appendLog("Polling timed out — stopped requesting /job-status.", "error")
        }
        return
      }

      try {
        const response = await apiFetch(`/job-status/${jobId}`)
        if (cancelled) return

        if (response.status === 404) {
          stopPolling()
          setJobFailed(true)
          setFailureMessage("Job not found.")
          appendLog("Job not found (404).", "error")
          return
        }

        if (response.status === 401 || response.status === 403) {
          stopPolling()
          setJobFailed(true)
          setFailureMessage("Authentication expired. Please sign in again.")
          appendLog("Auth error while polling job status.", "error")
          return
        }

        if (response.ok) {
          const data: JobStatus = await response.json()
          setLiveProgress(Number(data.progress) || 0)
          if (data.stage) setLiveStage(data.stage)
          if (
            data.chunks_done != null &&
            data.chunks_total != null &&
            data.chunks_total > 0
          ) {
            setChunkProgress(`${data.chunks_done}/${data.chunks_total} chunks`)
          }
          const detail =
            data.stage || data.chunks_done != null
              ? `${data.message || data.status}${
                  data.stage ? ` · ${data.stage}` : ""
                }${
                  data.chunks_done != null && data.chunks_total
                    ? ` · ${data.chunks_done}/${data.chunks_total}`
                    : ""
                }`
              : data.message || `Status: ${data.status}`
          appendLog(
            detail,
            isErrorStatus(data.status) ? "error" : "info",
          )

          if (isSuccessStatus(data.status)) {
            setIsComplete(true)
            stopPolling()
            fetchResult()
          } else if (
            isErrorStatus(data.status) ||
            isTerminalStatus(data.status)
          ) {
            setJobFailed(true)
            setFailureMessage(data.message || "Job failed.")
            stopPolling()
          }
        }
      } catch (error) {
        console.error("Polling error:", error)
        // Keep polling on transient network errors until POLL_TIMEOUT_MS.
        // Show a heartbeat so the UI does not look frozen when the API is busy.
        appendLog("Waiting for status (API busy or reconnecting)…", "info")
      } finally {
        inFlight = false
      }
    }

    pollInterval = setInterval(pollStatus, POLL_INTERVAL_MS)
    pollStatus()

    return () => {
      cancelled = true
      stopPolling()
    }
  }, [jobId])

  const fetchResult = async () => {
    try {
      const response = await apiFetch(
        `/job-result/${jobId}?_ts=${Date.now()}`,
        { cache: "no-store" },
      )
      if (response.ok) {
        const data: JobResult = await response.json()
        setResult(data)
        setChatMessages([
          {
            role: "assistant",
            content:
              "Your document is ready. I've read the summary and can answer questions about it.",
          },
        ])
      }
    } catch (error) {
      console.error("Error fetching result:", error)
    }
  }

  const handleCopy = () => {
    if (result?.final_summary) {
      navigator.clipboard.writeText(unwrapOuterMarkdownFence(result.final_summary))
      alert("Summary copied to clipboard!")
    }
  }

  const handleDownload = () => {
    if (result?.final_summary) {
      const blob = new Blob(
        [unwrapOuterMarkdownFence(result.final_summary)],
        { type: "text/markdown" },
      )
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = `summary-${result.filename || "document"}.md`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    }
  }

  const handleChatSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!chatInput.trim() || !result) return

    const userMsg = chatInput
    setChatMessages((prev) => [...prev, { role: "user", content: userMsg }])
    setChatInput("")
    setIsChatLoading(true)
    const startedAt = performance.now()

    try {
      const response = await apiFetch("/rag-query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document_id: result.document_id,
          query: userMsg,
        }),
      })

      const latencyMs = Math.round(performance.now() - startedAt)

      if (response.ok) {
        const data = await response.json()
        const sources: string[] = Array.isArray(data.sources) ? data.sources : []
        const retrievedChunks: RetrievedChunkMeta[] = Array.isArray(data.retrieved_chunks)
          ? data.retrieved_chunks
          : []
        setChatMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content: data.answer || "No answer returned.",
            meta: {
              confidence: data.confidence,
              reasoning_path: data.reasoning_path,
              model_used: data.model_used,
              entities_used: data.entities_used,
              missing_context: data.missing_context,
              sources,
              retrieved_chunks: retrievedChunks,
              knowledge_sources: data.knowledge_sources,
              skill: data.skill,
              latency_ms: latencyMs,
            },
          },
        ])
      } else {
        setChatMessages((prev) => [
          ...prev,
          { role: "assistant", content: "Sorry, I encountered an error answering that." },
        ])
      }
    } catch (error) {
      console.error("Chat error:", error)
      setChatMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Connection error." },
      ])
    } finally {
      setIsChatLoading(false)
    }
  }

  const preferenceLabel = formatPreferenceLabel(
    result?.processing_insights?.routing_preference,
  )

  const frontier = result ? resolveFrontierComparison(result) : null

  const showLiveFeed = !isComplete && !jobFailed && !pollTimedOut
  const showFailure = jobFailed || pollTimedOut

  return (
    <div className="flex">
      <Sidebar />
      <div className="flex-1">
        <TopBar />
        <main className="p-8">
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <h1 className="text-3xl font-bold mb-2">Job Status & Results</h1>
            <p className="text-muted-foreground mb-8">
              Job ID: {jobId || "Select a job below"}
            </p>

            <div className="grid grid-cols-1 xl:grid-cols-4 gap-6 mb-8">
              <div className="xl:col-span-1 space-y-4">
                <JobQueuePanel currentJobId={jobId} onSelectJob={selectJob} />
              </div>
              <div className="xl:col-span-3 space-y-6">
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                  <motion.div
                    initial={{ opacity: 0, x: -20 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: 0.2 }}
                    className="lg:col-span-1 space-y-4"
                  >
                <Card className="p-6 bg-gradient-to-br from-card to-card/50 border-border/50">
                  <h3 className="text-lg font-semibold mb-4">Job Report Card</h3>

                  {result ? (
                    <div className="space-y-4">
                      <div>
                        <p className="text-xs text-muted-foreground mb-1">Job ID</p>
                        <p className="font-mono text-sm break-all">{result.job_id}</p>
                      </div>

                      <div>
                        <p className="text-xs text-muted-foreground mb-1">Routing</p>
                        <p className="font-medium">{preferenceLabel}</p>
                      </div>

                      {(() => {
                        const cd = result.carbon_data as typeof result.carbon_data & {
                          estimated_baseline_pipeline_emissions_g?: number
                          estimated_optimized_pipeline_emissions_g?: number
                          assumptions_panel?: string
                          reporting_boundary_label?: string
                          routing_impact?: Record<string, number | string>
                          report_card?: Record<string, unknown> | null
                          uncertainty?: {
                            enabled?: boolean
                            optimized?: {
                              low_gco2e?: number
                              typical_gco2e?: number
                              high_gco2e?: number
                            }
                          }
                          pue?: number
                        }
                        const rc = asBreakdown(cd.report_card)
                        const bd = { ...asBreakdown(cd.breakdown), ...rc }
                        const numOr = (...vals: unknown[]) => {
                          for (const v of vals) {
                            if (v == null || v === "") continue
                            const n = Number(v)
                            if (Number.isFinite(n)) return n
                          }
                          return undefined
                        }
                        const fmtTok = (n?: number) =>
                          n != null ? Number(n).toLocaleString() : "—"
                        const fmtKwh = (n?: number) =>
                          n != null ? `${Number(n).toFixed(4)} kWh` : "—"
                        const fmtG = (n?: number, d = 1) =>
                          n != null ? `${Number(n).toFixed(d)} g` : "—"
                        const intensity = numOr(
                          rc.grid_carbon_intensity_gco2_kwh,
                          bd.grid_carbon_intensity_gco2_kwh,
                          cd.local_grid_gco2_kwh,
                        )
                        const zone =
                          rc.grid_zone ||
                          bd.grid_zone ||
                          cd.grid_zone ||
                          cd.compute_location
                        const updated =
                          rc.grid_updated_at ||
                          bd.grid_updated_at ||
                          bd.grid_datetime ||
                          cd.grid_updated_at ||
                          cd.grid_datetime
                        const baselineEst = numOr(
                          rc.estimated_baseline_pipeline_emissions_g,
                          cd.estimated_baseline_pipeline_emissions_g,
                          bd.estimated_baseline_pipeline_emissions_g,
                          bd.baseline_co2e_g,
                          cd.baseline_cost_gco2e,
                        )
                        const optimizedEst = numOr(
                          rc.estimated_optimized_pipeline_emissions_g,
                          cd.estimated_optimized_pipeline_emissions_g,
                          bd.estimated_optimized_pipeline_emissions_g,
                          bd.actual_co2e_g,
                          cd.actual_cost_gco2e,
                        )
                        const inputTokens = numOr(
                          rc.input_tokens,
                          bd.input_tokens,
                          cd.input_tokens,
                        )
                        const retrievedTokens = numOr(
                          rc.retrieved_context_tokens,
                          bd.retrieved_context_tokens,
                          cd.retrieved_context_tokens,
                        )
                        const generatedTokens = numOr(
                          rc.generated_tokens,
                          bd.generated_tokens,
                          cd.generated_tokens,
                        )
                        const effectiveTokens = numOr(
                          rc.effective_tokens,
                          bd.effective_tokens,
                          cd.effective_tokens,
                          inputTokens != null ||
                            retrievedTokens != null ||
                            generatedTokens != null
                            ? (inputTokens || 0) +
                                (retrievedTokens || 0) +
                                (generatedTokens || 0)
                            : undefined,
                        )
                        const baselineEnergy = numOr(
                          rc.baseline_energy_kwh,
                          bd.baseline_energy_kwh,
                          cd.baseline_energy_kwh,
                        )
                        const optimizedEnergy = numOr(
                          rc.optimized_energy_kwh,
                          bd.optimized_energy_kwh,
                          cd.actual_energy_kwh,
                        )
                        const stages = asBreakdown(
                          rc.optimized_stages_gco2e || bd.optimized_stages_gco2e,
                        )
                        const hasStages = Object.keys(stages).length > 0
                        const routing = asBreakdown(
                          rc.routing_impact || bd.routing_impact || cd.routing_impact,
                        )
                        const hasRouting = Object.keys(routing).length > 0
                        const uncertainty = (rc.uncertainty ||
                          bd.uncertainty ||
                          cd.uncertainty) as
                          | {
                              enabled?: boolean
                              optimized?: {
                                low_gco2e?: number
                                typical_gco2e?: number
                                high_gco2e?: number
                              }
                            }
                          | undefined
                        const assumptionsText = pickAssumptionsText(
                          rc.assumptions_panel as string | undefined,
                          cd.assumptions_panel,
                          bd.assumptions_panel as string | undefined,
                          cd.methodology,
                          result.methodology,
                        )
                        const savedGrams = numOr(
                          bd?.carbon_saved_g,
                          cd.carbon_saved_grams,
                          0,
                        )
                        const reductionPct = Number(
                          numOr(
                            bd?.reduction_percent,
                            cd.efficiency_percent,
                            0,
                          ),
                        )
                        const emissionsIncreased =
                          bd?.emissions_direction === "increased" ||
                          (cd as { emissions_direction?: string }).emissions_direction ===
                            "increased" ||
                          savedGrams < 0
                        const rows: [string, string][] = [
                          ["Input Tokens", fmtTok(inputTokens)],
                          ["Retrieved Context", fmtTok(retrievedTokens)],
                          ["Generated Tokens", fmtTok(generatedTokens)],
                          ["Effective Tokens", fmtTok(effectiveTokens)],
                          ["Estimated Baseline Energy", fmtKwh(baselineEnergy)],
                          ["Estimated Optimized Energy", fmtKwh(optimizedEnergy)],
                          [
                            "Grid Intensity",
                            intensity != null
                              ? `${Number(intensity).toFixed(0)} gCO₂e/kWh`
                              : "—",
                          ],
                          ["Estimated Baseline Pipeline", fmtG(baselineEst)],
                          ["Estimated Optimized Pipeline", fmtG(optimizedEst)],
                          [
                            emissionsIncreased
                              ? "Increased Emissions"
                              : "Estimated Carbon Saved",
                            fmtG(Math.abs(savedGrams)),
                          ],
                          [
                            "Estimated Reduction",
                            `${reductionPct.toFixed(1)}%`,
                          ],
                          ["Region", String(zone || "—")],
                          ["Last Updated", String(updated || "—")],
                        ]
                        return (
                          <>
                            <p className="text-xs text-muted-foreground">
                              {String(
                                cd.reporting_boundary_label ||
                                  bd.reporting_boundary_label ||
                                  "Operational Emissions (Boundary A) — estimates",
                              )}
                            </p>
                            <div className="grid grid-cols-2 gap-3">
                              <div className="rounded-lg border border-border/40 px-3 py-2">
                                <div className="flex items-center gap-1.5 mb-1">
                                  <Leaf className="w-3.5 h-3.5 text-green-400" />
                                  <span className="text-xs text-muted-foreground">
                                    {emissionsIncreased
                                      ? "Increased Emissions"
                                      : "Est. Carbon Saved"}
                                  </span>
                                </div>
                                <p
                                  className={`text-xl font-bold tabular-nums ${
                                    emissionsIncreased ? "text-rose-400" : ""
                                  }`}
                                >
                                  {fmtG(Math.abs(savedGrams))}
                                </p>
                              </div>
                              <div className="rounded-lg border border-border/40 px-3 py-2">
                                <div className="flex items-center gap-1.5 mb-1">
                                  <Zap className="w-3.5 h-3.5 text-blue-400" />
                                  <span className="text-xs text-muted-foreground">
                                    Est. Reduction
                                  </span>
                                </div>
                                <p
                                  className={`text-xl font-bold tabular-nums ${
                                    emissionsIncreased ? "text-rose-400" : ""
                                  }`}
                                >
                                  {reductionPct.toFixed(1)}%
                                </p>
                              </div>
                              <div className="rounded-lg border border-border/40 px-3 py-2">
                                <div className="flex items-center gap-1.5 mb-1">
                                  <Star className="w-3.5 h-3.5 text-amber-400" />
                                  <span className="text-xs text-muted-foreground">
                                    Est. Baseline Pipeline
                                  </span>
                                </div>
                                <p className="text-lg font-semibold tabular-nums">
                                  {fmtG(baselineEst)}
                                </p>
                              </div>
                              <div className="rounded-lg border border-border/40 px-3 py-2">
                                <div className="flex items-center gap-1.5 mb-1">
                                  <Leaf className="w-3.5 h-3.5 text-emerald-400" />
                                  <span className="text-xs text-muted-foreground">
                                    Est. Optimized Pipeline
                                  </span>
                                </div>
                                <p className="text-lg font-semibold tabular-nums">
                                  {fmtG(optimizedEst)}
                                </p>
                              </div>
                            </div>

                            {uncertainty?.enabled && uncertainty.optimized ? (
                              <div className="rounded-lg border border-border/40 px-3 py-2 space-y-0.5">
                                <p className="text-xs text-muted-foreground">
                                  Estimated CO₂e (typical / range)
                                </p>
                                <p className="text-sm font-semibold tabular-nums">
                                  {fmtG(uncertainty.optimized.typical_gco2e)}{" "}
                                  <span className="text-muted-foreground font-normal">
                                    ({fmtG(uncertainty.optimized.low_gco2e)} –{" "}
                                    {fmtG(uncertainty.optimized.high_gco2e)})
                                  </span>
                                </p>
                              </div>
                            ) : null}

                            {hasStages ? (
                              <div className="space-y-1.5">
                                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                                  Stage emissions (optimized)
                                </p>
                                {(
                                  [
                                    ["Inference", stages.inference_gco2e],
                                    ["Embeddings", stages.embedding_gco2e],
                                    ["Parsing", stages.parsing_gco2e],
                                    ["Chunking", stages.chunking_gco2e],
                                    ["Infrastructure", stages.infrastructure_gco2e],
                                    ["Total", stages.total_gco2e],
                                  ] as [string, unknown][]
                                ).map(([label, value]) =>
                                  value != null ? (
                                    <div
                                      key={label}
                                      className="flex justify-between gap-3 text-sm"
                                    >
                                      <span className="text-muted-foreground">{label}</span>
                                      <span className="tabular-nums font-medium">
                                        {fmtG(numOr(value))}
                                      </span>
                                    </div>
                                  ) : null
                                )}
                              </div>
                            ) : null}

                            {hasRouting ? (
                              <div className="space-y-1.5">
                                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                                  Routing impact
                                </p>
                                {(
                                  [
                                    ["Total chunks", routing.total_chunks],
                                    ["Light", routing.light_chunks],
                                    ["Medium", routing.medium_chunks],
                                    ["Heavy", routing.heavy_chunks],
                                    ["Escalated", routing.escalated_chunks],
                                    ["Compile calls", routing.compile_calls],
                                  ] as [string, unknown][]
                                ).map(([label, value]) =>
                                  value != null ? (
                                    <div
                                      key={label}
                                      className="flex justify-between gap-3 text-sm"
                                    >
                                      <span className="text-muted-foreground">{label}</span>
                                      <span className="tabular-nums font-medium">
                                        {String(value)}
                                      </span>
                                    </div>
                                  ) : null
                                )}
                              </div>
                            ) : null}

                            <div className="space-y-1.5 pt-1">
                              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                                Energy → PUE → grid → CO₂e
                              </p>
                              {rows.map(([label, value]) => (
                                <div
                                  key={label}
                                  className="flex items-baseline justify-between gap-3 text-sm"
                                >
                                  <span className="text-muted-foreground shrink-0">
                                    {label}
                                  </span>
                                  <span className="font-medium tabular-nums text-right break-all">
                                    {value}
                                  </span>
                                </div>
                              ))}
                            </div>

                            {(assumptionsText) && (
                              <div className="rounded-lg border border-border/40 bg-muted/20 px-3 py-2.5 space-y-1.5">
                                <div className="flex items-center gap-1.5">
                                  <Info className="w-3.5 h-3.5 text-muted-foreground" />
                                  <p className="text-xs font-medium text-muted-foreground">
                                    Assumptions
                                  </p>
                                </div>
                                <p className="text-xs text-muted-foreground leading-relaxed whitespace-pre-line">
                                  {assumptionsText}
                                </p>
                              </div>
                            )}
                          </>
                        )
                      })()}
                    </div>
                  ) : showFailure ? (
                    <div className="text-sm text-red-400 space-y-2">
                      <p className="font-medium">{pollTimedOut ? "Polling timed out" : "Job failed"}</p>
                      <p className="text-muted-foreground">{failureMessage}</p>
                    </div>
                  ) : (
                    <div className="text-muted-foreground text-sm">Waiting for results...</div>
                  )}
                </Card>

                {isComplete ? (
                  <>
                    <ExecutionRegionPanel
                      decision={result?.carbon_data?.region_decision}
                      fallbackIntensity={result?.carbon_data?.local_grid_gco2_kwh}
                      fallbackZone={result?.carbon_data?.grid_zone}
                      fallbackSource={result?.carbon_data?.grid_source}
                    />
                    <ProcessingInsightsPanel insights={result?.processing_insights} />
                    <PipelineIntelligencePanel insights={result?.processing_insights as any} />
                    <DocumentStructureViewer
                      tree={(result?.processing_insights as any)?.document_structure_tree}
                      diagnostics={(result?.processing_insights as any)?.structure_diagnostics}
                    />
                    <AdaptivePipelinePanel
                      insights={result?.processing_insights as any}
                    />
                  </>
                ) : null}
              </motion.div>

              <motion.div
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.2 }}
                className="lg:col-span-2"
              >
                {showLiveFeed ? (
                  <div className="space-y-4">
                    <Card className="p-4 bg-card/50 border-border/50 space-y-2">
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-muted-foreground">
                          {liveStage ? `Stage: ${liveStage}` : "Processing…"}
                          {chunkProgress ? ` · ${chunkProgress}` : ""}
                        </span>
                        <span className="tabular-nums font-medium">
                          {Math.round(liveProgress)}%
                        </span>
                      </div>
                      <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
                        <div
                          className="h-full bg-primary transition-all duration-300 ease-out"
                          style={{ width: `${Math.min(100, Math.max(0, liveProgress))}%` }}
                        />
                      </div>
                    </Card>
                    <LiveFeed logs={logs} />
                  </div>
                ) : showFailure ? (
                  <Card className="p-6 bg-card/50 border-border/50">
                    <h3 className="text-lg font-semibold mb-2 text-red-400">
                      {pollTimedOut ? "Polling stopped" : "Processing failed"}
                    </h3>
                    <p className="text-sm text-muted-foreground mb-4">
                      {failureMessage || "The job did not complete successfully."}
                    </p>
                    <LiveFeed logs={logs} />
                  </Card>
                ) : (
                  <Tabs defaultValue="summary" className="w-full">
                    <TabsList className="grid w-full grid-cols-2">
                      <TabsTrigger value="summary">Summary</TabsTrigger>
                      <TabsTrigger value="chat">Chat (RAG)</TabsTrigger>
                    </TabsList>

                    <TabsContent value="summary" className="space-y-4">
                      <Card className="p-6 md:p-8 bg-card/50 border-border/50">
                        <div className="flex gap-4 mb-6">
                          <Button
                            size="sm"
                            variant="outline"
                            className="gap-2 bg-transparent"
                            onClick={handleCopy}
                          >
                            <Copy className="w-4 h-4" />
                            Copy
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            className="gap-2 bg-transparent"
                            onClick={handleDownload}
                          >
                            <Download className="w-4 h-4" />
                            Download
                          </Button>
                        </div>
                        <div className="mx-auto w-full max-w-3xl">
                          <MarkdownContent content={result?.final_summary || ""} />
                        </div>
                      </Card>
                    </TabsContent>

                    <TabsContent value="chat" className="space-y-4">
                      <Card className="p-4 md:p-6 bg-card/50 border-border/50 h-[680px] flex flex-col">
                        <div className="flex-1 overflow-y-auto mb-4 space-y-4 p-1 md:p-2">
                          {chatMessages.map((msg, idx) => (
                            <div
                              key={idx}
                              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                            >
                              <div
                                className={`w-full rounded-xl p-3 md:p-4 space-y-1 ${
                                  msg.role === "user"
                                    ? "max-w-[85%] bg-primary text-primary-foreground"
                                    : "max-w-[95%] bg-muted/70"
                                }`}
                              >
                                {msg.role === "user" ? (
                                  <p className="text-sm whitespace-pre-wrap leading-relaxed">
                                    {msg.content}
                                  </p>
                                ) : (
                                  <>
                                    <MarkdownContent content={msg.content} compact />
                                    {msg.meta ? (
                                      <>
                                        <AnswerSources
                                          sources={msg.meta.sources}
                                          retrievedChunks={msg.meta.retrieved_chunks}
                                        />
                                        <AnswerMetaFooter
                                          modelUsed={msg.meta.model_used}
                                          confidence={msg.meta.confidence}
                                          latencyMs={msg.meta.latency_ms}
                                          documentsRetrieved={
                                            msg.meta.sources?.length ??
                                            msg.meta.retrieved_chunks?.length ??
                                            null
                                          }
                                          carbonSavedGrams={
                                            result?.carbon_data?.carbon_saved_grams
                                          }
                                        />
                                        <DeveloperDetails
                                          reasoningPath={msg.meta.reasoning_path}
                                          retrievedChunks={msg.meta.retrieved_chunks}
                                          modelUsed={msg.meta.model_used}
                                          skill={msg.meta.skill}
                                          confidence={msg.meta.confidence}
                                          latencyMs={msg.meta.latency_ms}
                                          entitiesUsed={msg.meta.entities_used}
                                          missingContext={msg.meta.missing_context}
                                          knowledgeSources={msg.meta.knowledge_sources}
                                          documentsRetrieved={
                                            msg.meta.sources?.length ??
                                            msg.meta.retrieved_chunks?.length ??
                                            null
                                          }
                                        />
                                      </>
                                    ) : null}
                                  </>
                                )}
                              </div>
                            </div>
                          ))}
                          {isChatLoading && (
                            <div className="text-sm text-muted-foreground">Thinking...</div>
                          )}
                        </div>
                        <form onSubmit={handleChatSubmit} className="flex gap-2">
                          <input
                            type="text"
                            value={chatInput}
                            onChange={(e) => setChatInput(e.target.value)}
                            placeholder="Ask a question about the document..."
                            className="flex-1 px-4 py-2 rounded-lg bg-background border border-border/50 placeholder-muted-foreground focus:outline-none focus:border-primary"
                          />
                          <Button type="submit" disabled={isChatLoading}>
                            Send
                          </Button>
                        </form>
                      </Card>
                    </TabsContent>
                  </Tabs>
                )}
              </motion.div>
                </div>

                {frontier?.summary_cards && frontier.comparison_models?.length ? (
                  <div className="mt-2 mb-4">
                    <CarbonComparisonDashboard
                      comparisonModels={frontier.comparison_models}
                      ourSystem={frontier.our_system}
                      summaryCards={frontier.summary_cards}
                      badges={frontier.badges}
                      chartBars={frontier.chart_bars}
                      methodology={
                        frontier.methodology ||
                        result?.methodology ||
                        result?.carbon_data?.methodology
                      }
                      breakdown={result?.carbon_data?.breakdown || null}
                      carbonData={result?.carbon_data || null}
                    />
                  </div>
                ) : null}
              </div>
            </div>
          </motion.div>
        </main>
      </div>
    </div>
  )
}

export default function ResultsPage() {
  return (
    <Suspense fallback={<div>Loading...</div>}>
      <ResultsContent />
    </Suspense>
  )
}
