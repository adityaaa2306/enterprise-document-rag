"use client"

import dynamic from "next/dynamic"
import { motion } from "framer-motion"
import { useState, useEffect, Suspense, useCallback, useRef } from "react"
import { useSearchParams, useRouter } from "next/navigation"
import { Sidebar } from "@/components/sidebar"
import { TopBar } from "@/components/top-bar"
import { GuestOwnerGate } from "@/components/guest-owner-gate"
import { LiveFeed } from "@/components/live-feed"
import { ExecutionGraph } from "@/components/execution-graph"
import { JobQueuePanel } from "@/components/job-queue-panel"
import { Card } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { apiFetch } from "@/lib/api"
import { getLastJobId, rememberJobId } from "@/lib/job-session"
import { isUuid } from "@/lib/input-validation"
import type { ProcessingInsightsData } from "@/components/processing-insights"
import { unwrapOuterMarkdownFence } from "@/lib/utils"
import { stripSummaryMetrics } from "@/lib/strip-summary-metrics"
import {
  cloneJobResult,
  isMetricsReadyFromResult,
  isMetricsReadyFromStatus,
  resultSyncKey,
} from "@/lib/job-result-sync"
import { publishFinalizedJobResult } from "@/lib/finalized-metrics-store"
import {
  ResultsPanelSkeleton,
  SummarySkeleton,
  ChatSkeleton,
} from "@/components/loading-skeletons"

const JobResultsPanel = dynamic(
  () =>
    import("@/components/job-results-panel").then((m) => ({
      default: m.JobResultsPanel,
    })),
  { ssr: false, loading: () => <ResultsPanelSkeleton /> },
)

const ExpandableSummary = dynamic(
  () =>
    import("@/components/expandable-summary").then((m) => ({
      default: m.ExpandableSummary,
    })),
  { ssr: false, loading: () => <SummarySkeleton /> },
)

const DocumentChat = dynamic(
  () =>
    import("@/components/document-chat").then((m) => ({
      default: m.DocumentChat,
    })),
  { ssr: false, loading: () => <ChatSkeleton /> },
)

/** Poll every 1.5s; skip ticks while a request is in flight (avoids stampede). */
const POLL_INTERVAL_MS = 750
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

/** Session cache so revisiting Results with the same job_id skips a duplicate fetch. */
const resultCache = new Map<string, JobResult>()

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
  chunks_queued?: number | null
  chunks_running?: number | null
  chunks_failed?: number | null
  chunks_retrying?: number | null
  partial?: Record<string, unknown> | null
  workers_busy?: number | null
  workers_total?: number | null
  avg_latency_ms?: number | null
  carbon_g?: number | null
  remaining_tasks?: number | null
  eta_sec?: number | null
  dag?: Record<string, unknown> | null
  summary_ready?: boolean | null
  background_phase?: string | null
  background_message?: string | null
  metrics_ready?: boolean | null
}

interface JobResult {
  job_id: string
  document_id: string
  filename: string
  final_summary: string
  summary_ready?: boolean
  background?: { phase?: string; message?: string } | null
  carbon_data: Record<string, unknown> & {
    carbon_saved_grams?: number
  }
  processing_insights?: ProcessingInsightsData | null
  comparison_models?: unknown
  our_system?: unknown
  summary_cards?: unknown
  badges?: string[] | null
  chart_bars?: unknown
  methodology?: string | null
}

function syncTrace(transition: string, detail?: Record<string, unknown>) {
  // eslint-disable-next-line no-console
  console.info("SYNC_LIFECYCLE", { transition, t: Date.now(), ...detail })
}

function isSummaryReadyFromStatus(data: JobStatus): boolean {
  if (data.summary_ready === true) return true
  const msg = (data.message || "").toLowerCase()
  return msg.includes("summary ready") || isSuccessStatus(data.status)
}

function ResultsContent() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const urlJobId = searchParams.get("job_id")
  const [jobId, setJobId] = useState<string | null>(urlJobId)

  const [isComplete, setIsComplete] = useState(false)
  const [metricsReady, setMetricsReady] = useState(false)
  const [jobFailed, setJobFailed] = useState(false)
  const [pollTimedOut, setPollTimedOut] = useState(false)
  const [failureMessage, setFailureMessage] = useState<string | null>(null)
  const [logs, setLogs] = useState<any[]>([])
  const [liveProgress, setLiveProgress] = useState(0)
  const [liveStage, setLiveStage] = useState<string | null>(null)
  const [chunkProgress, setChunkProgress] = useState<string | null>(null)
  const [liveDag, setLiveDag] = useState<Record<string, unknown> | null>(null)
  const [streamMeta, setStreamMeta] = useState<{
    workersBusy?: number | null
    workersTotal?: number | null
    avgLatencyMs?: number | null
    carbonG?: number | null
    remaining?: number | null
    etaSec?: number | null
  }>({})
  const [bgBanner, setBgBanner] = useState<string | null>(null)
  const [result, setResult] = useState<JobResult | null>(null)
  /** True only while waiting for the *first* result payload (never hide existing result). */
  const [awaitingFirstResult, setAwaitingFirstResult] = useState(false)
  const [refreshingResult, setRefreshingResult] = useState(false)
  const fetchGen = useRef(0)
  /** Coalesce concurrent /job-result calls — stampede was discarding every response. */
  const inflightResultRef = useRef<Promise<JobResult | null> | null>(null)
  const resultRef = useRef<JobResult | null>(null)

  useEffect(() => {
    syncTrace("ResultsPage mounted", { job_id: urlJobId })
  }, [urlJobId])

  // Restore last job when visiting /results without query (sidebar nav)
  useEffect(() => {
    if (urlJobId) {
      if (!isUuid(urlJobId)) {
        setJobId(null)
        return
      }
      setJobId(urlJobId)
      rememberJobId(urlJobId)
      return
    }
    const last = getLastJobId()
    if (last && isUuid(last)) {
      setJobId(last)
      router.replace(`/results?job_id=${last}`)
    }
  }, [urlJobId, router])

  const selectJob = useCallback(
    (id: string) => {
      if (!isUuid(id)) return
      rememberJobId(id)
      setJobId(id)
      setIsComplete(false)
      setMetricsReady(false)
      setJobFailed(false)
      setPollTimedOut(false)
      setFailureMessage(null)
      setLogs([])
      setResult(null)
      resultRef.current = null
      resultCache.delete(id)
      setAwaitingFirstResult(false)
      setRefreshingResult(false)
      setLiveProgress(0)
      setLiveStage(null)
      setChunkProgress(null)
      setBgBanner(null)
      inflightResultRef.current = null
      router.replace(`/results?job_id=${id}`)
      syncTrace("Job selected / store reset", { job_id: id })
    },
    [router],
  )

  const applyResult = useCallback((id: string, data: JobResult, path: string) => {
    // Always replace with a new object identity so React + useMemo dependents re-render.
    const next = cloneJobResult(data) as JobResult
    const prevKey = resultSyncKey(resultRef.current)
    const nextKey = resultSyncKey(next)
    resultCache.set(id, next)
    resultRef.current = next
    setResult(next)
    setAwaitingFirstResult(false)
    setRefreshingResult(false)
    const ready = isMetricsReadyFromResult(next)
    if (ready) setMetricsReady(true)
    if ((next.final_summary || "").trim()) setIsComplete(true)
    // Shared Dashboard ↔ Results source of truth (same finalized blob + metrics).
    if (ready) {
      publishFinalizedJobResult(id, next as any)
    }
    syncTrace("Store updated", {
      job_id: id,
      path,
      metrics_ready: ready,
      sync_key: nextKey,
      replaced: prevKey !== nextKey,
      has_summary: Boolean(next.final_summary),
      chunks: (next.carbon_data as { total_chunks?: number } | undefined)?.total_chunks,
      baseline: Number((next.carbon_data as { baseline_cost_gco2e?: number } | undefined)?.baseline_cost_gco2e || 0),
      bg: next.background?.phase,
    })
    syncTrace("Loading=false", { job_id: id, path })
    syncTrace("Results component rendered", { job_id: id, path, sync_key: nextKey })
  }, [])

  const fetchResult = useCallback(
    async (id: string, opts?: { force?: boolean; fresh?: boolean }) => {
      const force = Boolean(opts?.force)
      const fresh = Boolean(opts?.fresh)
      if (!force) {
        const cached = resultCache.get(id)
        if (cached && isMetricsReadyFromResult(cached)) {
          applyResult(id, cached, "cache_hit")
          return cached
        }
      }

      // Coalesce only soft polls. Fresh/force-after-ready must not reuse a
      // Summary Ready in-flight response that started before background finished.
      if (!fresh && inflightResultRef.current) {
        syncTrace("JobResult fetch coalesced", { job_id: id, force })
        return inflightResultRef.current
      }
      if (fresh && inflightResultRef.current) {
        syncTrace("JobResult awaiting prior inflight before fresh fetch", { job_id: id })
        try {
          await inflightResultRef.current
        } catch {
          /* ignore */
        }
      }

      const hasResult = Boolean(resultRef.current?.final_summary)
      if (hasResult) {
        setRefreshingResult(true)
      } else {
        setAwaitingFirstResult(true)
      }
      syncTrace("JobResult fetched (start)", { job_id: id, force, fresh, soft: hasResult })

      const req = (async (): Promise<JobResult | null> => {
        const gen = ++fetchGen.current
        try {
          const response = await apiFetch(`/job-result/${id}?_ts=${Date.now()}`, {
            cache: "no-store",
          })
          if (!response.ok) {
            syncTrace("JobResult fetch failed", {
              job_id: id,
              status: response.status,
              gen,
            })
            if (response.status === 403 || response.status === 404) {
              try {
                const { clearLastJobId, getLastJobId } = await import("@/lib/job-session")
                if (getLastJobId() === id) clearLastJobId()
              } catch {
                /* ignore */
              }
            }
            // Surface repeated 400s so we don't spin forever on skeletons
            if (response.status === 400 && !resultRef.current) {
              const detail = await response
                .clone()
                .json()
                .then((b: { detail?: string }) => b?.detail)
                .catch(() => null)
              syncTrace("JobResult not ready", { job_id: id, detail })
            }
            return resultRef.current
          }
          const data: JobResult = await response.json()
          // Always replace React state with the newest payload (immutable copy inside applyResult).
          applyResult(id, data, force || fresh ? "force_fetch" : "fetch")
          syncTrace("Cache invalidated", { job_id: id, gen, sync_key: resultSyncKey(data) })
          syncTrace("Skeleton removed", {
            job_id: id,
            has_result: true,
            metrics_ready: isMetricsReadyFromResult(data),
          })
          return resultRef.current
        } catch (error) {
          console.error("Error fetching result:", error)
          syncTrace("JobResult fetch error", {
            job_id: id,
            error: String(error),
          })
          return resultRef.current
        } finally {
          inflightResultRef.current = null
          setAwaitingFirstResult(false)
          setRefreshingResult(false)
        }
      })()

      inflightResultRef.current = req
      return req
    },
    [applyResult],
  )

  const refreshAll = useCallback(async () => {
    syncTrace("Manual Refresh", { job_id: jobId, path: "queue_refresh_button" })
    if (jobId) {
      await fetchResult(jobId, { force: true, fresh: true })
    }
  }, [jobId, fetchResult])

  useEffect(() => {
    if (!jobId) return
    rememberJobId(jobId)

    // Instant path: only skip poll when cached result already has full metrics.
    const cached = resultCache.get(jobId)
    if (cached && isMetricsReadyFromResult(cached)) {
      applyResult(jobId, cached, "cache_hit_metrics_ready")
      setIsComplete(true)
      setMetricsReady(true)
      setLiveProgress(100)
      setBgBanner(null)
      return
    }
    if (cached) {
      // Show summary early but keep polling for background metrics.
      applyResult(jobId, cached, "cache_hit_summary_only")
      setIsComplete(true)
      setMetricsReady(false)
    }

    let cancelled = false
    let pollInterval: ReturnType<typeof setInterval> | undefined
    let inFlight = false
    let lastResultFetchAt = 0
    const startedAt = Date.now()
    const RESULT_REFETCH_MS = 1500

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

    const applyStatusFields = (data: JobStatus) => {
      setLiveProgress(Number(data.progress) || 0)
      if (data.stage) setLiveStage(data.stage)
      const dagPayload =
        (data.dag as Record<string, unknown> | null) ||
        ((data.partial as { dag?: Record<string, unknown> } | null)?.dag ?? null)
      if (dagPayload) setLiveDag(dagPayload)
      setStreamMeta({
        workersBusy: data.workers_busy ?? null,
        workersTotal: data.workers_total ?? null,
        avgLatencyMs: data.avg_latency_ms ?? null,
        carbonG: data.carbon_g ?? null,
        remaining: data.remaining_tasks ?? null,
        etaSec: data.eta_sec ?? null,
      })
      if (
        data.chunks_done != null &&
        data.chunks_total != null &&
        data.chunks_total > 0
      ) {
        const bits = [
          `completed ${data.chunks_done}/${data.chunks_total}`,
          data.chunks_running != null ? `running ${data.chunks_running}` : "",
          data.chunks_queued != null ? `queued ${data.chunks_queued}` : "",
          data.chunks_failed != null && data.chunks_failed > 0
            ? `failed ${data.chunks_failed}`
            : "",
          data.chunks_retrying != null && data.chunks_retrying > 0
            ? `retrying ${data.chunks_retrying}`
            : "",
        ].filter(Boolean)
        setChunkProgress(bits.join(" · "))
      }
      const bgMsg = data.background_message || data.background_phase
      if (bgMsg && !isMetricsReadyFromStatus(data)) {
        setBgBanner(String(bgMsg))
      } else if (isMetricsReadyFromStatus(data)) {
        setBgBanner(null)
      }
    }

    const finishMetrics = async (
      reason: string,
      already?: JobResult | null,
    ): Promise<boolean> => {
      syncTrace("Background Complete → Final fetch", { job_id: jobId, reason })
      let data =
        already && isMetricsReadyFromResult(already)
          ? already
          : await fetchResult(jobId, { force: true, fresh: true })
      if (cancelled) return false
      // Status can flip to metrics_ready slightly before /job-result is rewritten.
      // Never stop polling or freeze metricsReady on a Summary Ready stub.
      if (!isMetricsReadyFromResult(data)) {
        syncTrace("Result still incomplete after claimed ready — keep polling", {
          job_id: jobId,
          reason,
          sync_key: resultSyncKey(data),
          phase: data?.background?.phase,
          baseline: Number(
            (data?.carbon_data as { baseline_cost_gco2e?: number } | undefined)
              ?.baseline_cost_gco2e || 0,
          ),
        })
        lastResultFetchAt = 0
        return false
      }
      // One more immutable apply so cards definitely see the final object.
      if (data) applyResult(jobId, data, "finish_metrics")
      setIsComplete(true)
      setMetricsReady(true)
      setLiveProgress(100)
      setBgBanner(null)
      stopPolling()
      syncTrace("JobStatus updated", {
        job_id: jobId,
        path: "metrics_ready",
        sync_key: resultSyncKey(data),
        chunks: (data?.carbon_data as { total_chunks?: number } | undefined)?.total_chunks,
      })
      appendLog("Search Ready · metrics populated.", "info")
      return true
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
          syncTrace("Polling update received", {
            job_id: jobId,
            status: data.status,
            progress: data.progress,
            summary_ready: data.summary_ready,
            background_phase: data.background_phase,
            metrics_ready: data.metrics_ready,
            message: data.message,
          })
          syncTrace("JobStatus updated", {
            job_id: jobId,
            status: data.status,
            metrics_ready: data.metrics_ready,
          })
          applyStatusFields(data)

          const detail = data.message || `Status: ${data.status}`
          appendLog(
            [
              detail,
              data.stage ? `· ${data.stage}` : "",
              data.background_phase ? `· bg:${data.background_phase}` : "",
            ]
              .filter(Boolean)
              .join(" "),
            isErrorStatus(data.status) ? "error" : "info",
          )

          if (isErrorStatus(data.status) || (isTerminalStatus(data.status) && !isSuccessStatus(data.status))) {
            setJobFailed(true)
            setFailureMessage(data.message || "Job failed.")
            stopPolling()
            return
          }

          // Summary Ready: show summary ASAP, keep polling for background metrics.
          if (isSummaryReadyFromStatus(data) || isSuccessStatus(data.status)) {
            setIsComplete(true)
            const now = Date.now()
            const cachedResult = resultCache.get(jobId) || resultRef.current
            const shouldRefetch =
              !cachedResult?.final_summary ||
              now - lastResultFetchAt >= RESULT_REFETCH_MS ||
              isMetricsReadyFromStatus(data)
            let latest = cachedResult || null
            if (shouldRefetch) {
              lastResultFetchAt = now
              latest = await fetchResult(jobId, {
                force: true,
                fresh: isMetricsReadyFromStatus(data),
              })
            }
            if (
              isMetricsReadyFromStatus(data) ||
              isMetricsReadyFromResult(latest)
            ) {
              const done = await finishMetrics("status_or_result.metrics_ready", latest)
              if (done) return
              // Keep interval alive until /job-result carries dashboard metrics.
            }
            // Critical fix: do NOT stopPolling here — wait for Background Complete.
            setBgBanner(
              data.background_message ||
                data.background_phase ||
                latest?.background?.message ||
                "Background Processing…",
            )
            return
          }
        }
      } catch (error) {
        console.error("Polling error:", error)
        appendLog("Waiting for status (API busy or reconnecting)…", "info")
      } finally {
        inFlight = false
      }
    }

    ;(async () => {
      if (!resultRef.current) setAwaitingFirstResult(true)
      try {
        // Single path: status poll + shared fetchResult (no parallel stampede).
        const statusRes = await apiFetch(`/job-status/${jobId}`)
        if (cancelled) return

        let statusData: JobStatus | null = null
        if (statusRes.ok) {
          const statusPayload: JobStatus = await statusRes.json()
          statusData = statusPayload
          syncTrace("Polling update received", {
            job_id: jobId,
            path: "initial",
            status: statusPayload.status,
            metrics_ready: statusPayload.metrics_ready,
          })
          applyStatusFields(statusPayload)
          appendLog(
            statusPayload.message || `Status: ${statusPayload.status}`,
            isErrorStatus(statusPayload.status) ? "error" : "info",
          )
        }

        if (statusRes.status === 404) {
          setJobFailed(true)
          setFailureMessage("Job not found.")
          setAwaitingFirstResult(false)
          appendLog("Job not found (404).", "error")
          return
        }
        if (statusRes.status === 401 || statusRes.status === 403) {
          setJobFailed(true)
          setFailureMessage("Authentication expired. Please sign in again.")
          setAwaitingFirstResult(false)
          return
        }

        if (
          statusData &&
          (isErrorStatus(statusData.status) ||
            (isTerminalStatus(statusData.status) && !isSuccessStatus(statusData.status)))
        ) {
          setJobFailed(true)
          setFailureMessage(statusData.message || "Job failed.")
          setAwaitingFirstResult(false)
          return
        }

        if (
          statusData &&
          (isSummaryReadyFromStatus(statusData) || isSuccessStatus(statusData.status))
        ) {
          setIsComplete(true)
          const data = await fetchResult(jobId, { force: true, fresh: true })
          if (cancelled) return
          if (
            isMetricsReadyFromResult(data) ||
            isMetricsReadyFromStatus(statusData)
          ) {
            const done = await finishMetrics("initial.metrics_ready", data)
            if (done) return
            // Fall through to start interval — status raced ahead of result blob.
          }
          setBgBanner(
            statusData.background_message ||
              data?.background?.message ||
              "Background Processing…",
          )
          appendLog("Summary Ready · waiting for background metrics…", "info")
        }
      } catch (error) {
        console.error("Initial result race error:", error)
      } finally {
        if (!cancelled && !resultRef.current) setAwaitingFirstResult(false)
      }

      if (cancelled) return
      // Keep polling until metrics_ready — even after Summary Ready / status=complete.
      pollInterval = setInterval(pollStatus, POLL_INTERVAL_MS)
      void pollStatus()
    })()

    return () => {
      cancelled = true
      stopPolling()
      inflightResultRef.current = null
    }
  }, [jobId, fetchResult, applyResult])

  const handleCopy = () => {
    if (result?.final_summary) {
      navigator.clipboard.writeText(
        stripSummaryMetrics(unwrapOuterMarkdownFence(result.final_summary)),
      )
      alert("Summary copied to clipboard!")
    }
  }

  const handleDownload = () => {
    if (result?.final_summary) {
      const blob = new Blob(
        [stripSummaryMetrics(unwrapOuterMarkdownFence(result.final_summary))],
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

  const showLiveFeed = Boolean(jobId) && !metricsReady && !jobFailed && !pollTimedOut
  const showFailure = jobFailed || pollTimedOut
  const summaryMarkdown = result?.final_summary
    ? stripSummaryMetrics(unwrapOuterMarkdownFence(result.final_summary))
    : ""
  /** Defer sidebar queue polls whenever a job is open so /job-result wins the wire. */
  const deferQueuePolling = Boolean(jobId) && !jobFailed && !pollTimedOut
  const metricsPending = Boolean(isComplete && result && !metricsReady)
  /** Skeleton only when complete but result not yet applied — never gate on soft refresh. */
  const showResultsSkeleton = Boolean(isComplete && !result && !showFailure)
  const showResults = Boolean(isComplete && result)

  useEffect(() => {
    syncTrace("Results render gate", {
      job_id: jobId,
      isComplete,
      metricsReady,
      hasResult: Boolean(result),
      awaitingFirstResult,
      refreshingResult,
      showResultsSkeleton,
      showResults,
      showLiveFeed,
    })
    if (showResults) {
      syncTrace("Charts rendered", { job_id: jobId })
      syncTrace("Summary rendered", {
        job_id: jobId,
        len: summaryMarkdown.length,
      })
    }
  }, [
    jobId,
    isComplete,
    metricsReady,
    result,
    awaitingFirstResult,
    refreshingResult,
    showResultsSkeleton,
    showResults,
    showLiveFeed,
    summaryMarkdown.length,
  ])

  return (
    <GuestOwnerGate>
    <div className="flex">
      <Sidebar />
      <div className="flex-1 min-w-0">
        <TopBar />
        <main className="p-6 md:p-8">
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <h1 className="text-3xl font-bold mb-2">Job Status & Results</h1>
            <p className="text-muted-foreground mb-6">
              Job ID: {jobId || "Select a job below"}
              {refreshingResult ? (
                <span className="ml-2 text-xs text-muted-foreground">(updating…)</span>
              ) : null}
            </p>

            <div className="grid grid-cols-1 xl:grid-cols-4 gap-6">
              <div className="xl:col-span-1 space-y-4">
                <JobQueuePanel
                  currentJobId={jobId}
                  onSelectJob={selectJob}
                  onRefreshResults={refreshAll}
                  autoSelectLatest
                  deferPolling={deferQueuePolling}
                />
              </div>

              <div className="xl:col-span-3 space-y-6">
                {showLiveFeed ? (
                  <div className="space-y-4">
                    <ExecutionGraph
                      dag={liveDag as any}
                      workersBusy={streamMeta.workersBusy}
                      workersTotal={streamMeta.workersTotal}
                      avgLatencyMs={streamMeta.avgLatencyMs}
                      carbonG={streamMeta.carbonG}
                      remaining={streamMeta.remaining}
                      etaSec={streamMeta.etaSec}
                      progress={liveProgress}
                    />
                    <div className="text-xs text-muted-foreground font-mono">
                      {liveStage ? `Stage: ${liveStage}` : "Processing…"}
                      {chunkProgress ? ` · ${chunkProgress}` : ""}
                    </div>
                    <LiveFeed logs={logs} />
                  </div>
                ) : null}

                {showFailure ? (
                  <Card className="p-6 bg-card/50 border-border/50">
                    <h3 className="text-lg font-semibold mb-2 text-red-400">
                      {pollTimedOut ? "Polling stopped" : "Processing failed"}
                    </h3>
                    <p className="text-sm text-muted-foreground mb-4">
                      {failureMessage || "The job did not complete successfully."}
                    </p>
                    <LiveFeed logs={logs} />
                  </Card>
                ) : null}

                {showResultsSkeleton ? <ResultsPanelSkeleton /> : null}

                {showResults && result ? (
                  <>
                    {(metricsPending || bgBanner) && (
                      <div className="rounded-md border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-sm text-muted-foreground">
                        <span className="font-medium text-foreground">Background Processing: </span>
                        {bgBanner ||
                          result.background?.message ||
                          result.background?.phase ||
                          "Updating carbon metrics & search index…"}
                      </div>
                    )}
                    <JobResultsPanel
                      key={resultSyncKey(result)}
                      jobId={jobId}
                      result={result as any}
                      metricsPending={metricsPending}
                    />

                    <Tabs defaultValue="summary" className="w-full">
                      <TabsList className="grid w-full grid-cols-2">
                        <TabsTrigger value="summary">Summary</TabsTrigger>
                        <TabsTrigger value="chat">Chat (RAG)</TabsTrigger>
                      </TabsList>

                      <TabsContent value="summary" className="space-y-4">
                        <ExpandableSummary
                          content={summaryMarkdown}
                          onCopy={handleCopy}
                          onDownload={handleDownload}
                          collapsedMaxPx={220}
                        />
                      </TabsContent>

                      <TabsContent value="chat" className="space-y-4">
                        <DocumentChat
                          key={(result as any).document_id}
                          result={result as any}
                        />
                      </TabsContent>
                    </Tabs>
                  </>
                ) : null}

                {!jobId && !showLiveFeed && !showFailure && !isComplete ? (
                  <Card className="p-6 bg-card/50 border-border/50">
                    <p className="text-sm text-muted-foreground">
                      Loading your latest job…
                    </p>
                  </Card>
                ) : null}

                {jobId && !showLiveFeed && !showFailure && !isComplete ? (
                  <Card className="p-6 bg-card/50 border-border/50">
                    <p className="text-sm text-muted-foreground">
                      Waiting for job status…
                    </p>
                  </Card>
                ) : null}
              </div>
            </div>
          </motion.div>
        </main>
      </div>
    </div>
    </GuestOwnerGate>
  )
}

export default function ResultsPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen">
          <div className="flex-1 p-8">
            <ResultsPanelSkeleton />
          </div>
        </div>
      }
    >
      <ResultsContent />
    </Suspense>
  )
}
