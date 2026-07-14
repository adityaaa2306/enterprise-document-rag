"use client"

import { motion } from "framer-motion"
import { useState, useEffect, Suspense, useCallback } from "react"
import { useSearchParams, useRouter } from "next/navigation"
import { Sidebar } from "@/components/sidebar"
import { TopBar } from "@/components/top-bar"
import { LiveFeed } from "@/components/live-feed"
import { JobQueuePanel } from "@/components/job-queue-panel"
import { JobResultsPanel } from "@/components/job-results-panel"
import { ExpandableSummary } from "@/components/expandable-summary"
import { DocumentChat } from "@/components/document-chat"
import { Card } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { apiFetch } from "@/lib/api"
import { getLastJobId, rememberJobId } from "@/lib/job-session"
import type { ProcessingInsightsData } from "@/components/processing-insights"
import { unwrapOuterMarkdownFence } from "@/lib/utils"
import { stripSummaryMetrics } from "@/lib/strip-summary-metrics"

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

interface JobResult {
  job_id: string
  document_id: string
  filename: string
  final_summary: string
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
      }
    } catch (error) {
      console.error("Error fetching result:", error)
    }
  }

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

  const showLiveFeed = Boolean(jobId) && !isComplete && !jobFailed && !pollTimedOut
  const showFailure = jobFailed || pollTimedOut
  const summaryMarkdown = result?.final_summary
    ? stripSummaryMetrics(unwrapOuterMarkdownFence(result.final_summary))
    : ""

  return (
    <div className="flex">
      <Sidebar />
      <div className="flex-1 min-w-0">
        <TopBar />
        <main className="p-6 md:p-8">
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <h1 className="text-3xl font-bold mb-2">Job Status & Results</h1>
            <p className="text-muted-foreground mb-6">
              Job ID: {jobId || "Select a job below"}
            </p>

            <div className="grid grid-cols-1 xl:grid-cols-4 gap-6">
              <div className="xl:col-span-1 space-y-4">
                <JobQueuePanel
                  currentJobId={jobId}
                  onSelectJob={selectJob}
                  autoSelectLatest
                />
              </div>

              <div className="xl:col-span-3 space-y-6">
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

                {isComplete && !result ? (
                  <Card className="p-6 bg-card/50 border-border/50">
                    <p className="text-sm text-muted-foreground">
                      Job complete — loading results…
                    </p>
                  </Card>
                ) : null}

                {isComplete && result ? (
                  <>
                    <JobResultsPanel result={result as any} />

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
                        <DocumentChat key={(result as any).document_id} result={result as any} />
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
  )
}

export default function ResultsPage() {
  return (
    <Suspense fallback={<div>Loading...</div>}>
      <ResultsContent />
    </Suspense>
  )
}
