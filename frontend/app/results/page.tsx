"use client"

import { motion } from "framer-motion"
import { useState, useEffect, Suspense } from "react"
import { useSearchParams } from "next/navigation"
import { Sidebar } from "@/components/sidebar"
import { TopBar } from "@/components/top-bar"
import { LiveFeed } from "@/components/live-feed"
import { Card } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Leaf, Zap, Star, Copy, Download, Info } from "lucide-react"
import { Button } from "@/components/ui/button"
import { apiFetch } from "@/lib/api"
import {
  ProcessingInsightsPanel,
  type ProcessingInsightsData,
} from "@/components/processing-insights"
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

/** Poll every 3s (within the 2–5s target range). */
const POLL_INTERVAL_MS = 3000
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
  return s === "error" || s === "failed" || s === "failure"
}

interface JobStatus {
  status: string
  progress: number
  message: string
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
  breakdown?: CarbonBreakdown | null
  methodology?: string | null
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
  const jobId = searchParams.get("job_id")

  const [isComplete, setIsComplete] = useState(false)
  const [jobFailed, setJobFailed] = useState(false)
  const [pollTimedOut, setPollTimedOut] = useState(false)
  const [failureMessage, setFailureMessage] = useState<string | null>(null)
  const [logs, setLogs] = useState<any[]>([])
  const [result, setResult] = useState<JobResult | null>(null)
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [chatInput, setChatInput] = useState("")
  const [isChatLoading, setIsChatLoading] = useState(false)

  useEffect(() => {
    if (!jobId) return

    let cancelled = false
    let pollInterval: ReturnType<typeof setInterval> | undefined
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
      if (cancelled) return

      if (Date.now() - startedAt > POLL_TIMEOUT_MS) {
        stopPolling()
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
          appendLog(
            data.message || `Status: ${data.status}`,
            isErrorStatus(data.status) ? "error" : "info",
          )

          if (isSuccessStatus(data.status)) {
            setIsComplete(true)
            stopPolling()
            fetchResult()
          } else if (isErrorStatus(data.status) || isTerminalStatus(data.status)) {
            setJobFailed(true)
            setFailureMessage(data.message || "Job failed.")
            stopPolling()
          }
        }
      } catch (error) {
        console.error("Polling error:", error)
        // Keep polling on transient network errors until POLL_TIMEOUT_MS
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
            <p className="text-muted-foreground mb-8">Job ID: {jobId || "Loading..."}</p>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
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
                        const cd = result.carbon_data
                        const bd = cd.breakdown
                        const fmtTok = (n?: number) =>
                          n != null ? Number(n).toLocaleString() : "—"
                        const fmtKwh = (n?: number) =>
                          n != null ? `${Number(n).toFixed(4)} kWh` : "—"
                        const fmtG = (n?: number, d = 1) =>
                          n != null ? `${Number(n).toFixed(d)} g` : "—"
                        const intensity =
                          bd?.grid_carbon_intensity_gco2_kwh ?? cd.local_grid_gco2_kwh
                        const zone = bd?.grid_zone || cd.grid_zone || cd.compute_location
                        const updated =
                          bd?.grid_updated_at || bd?.grid_datetime || cd.grid_datetime
                        const rows: [string, string][] = [
                          ["Input Tokens", fmtTok(bd?.input_tokens)],
                          ["Retrieved Context", fmtTok(bd?.retrieved_context_tokens)],
                          ["Generated Tokens", fmtTok(bd?.generated_tokens)],
                          ["Effective Tokens", fmtTok(bd?.effective_tokens)],
                          [
                            "Baseline Energy",
                            fmtKwh(bd?.baseline_energy_kwh ?? cd.baseline_energy_kwh),
                          ],
                          [
                            "Optimized Energy",
                            fmtKwh(bd?.optimized_energy_kwh ?? cd.actual_energy_kwh),
                          ],
                          [
                            "Grid Intensity",
                            intensity != null
                              ? `${Number(intensity).toFixed(0)} gCO₂e/kWh`
                              : "—",
                          ],
                          [
                            "Baseline CO₂",
                            fmtG(bd?.baseline_co2e_g ?? cd.baseline_cost_gco2e),
                          ],
                          [
                            "Actual CO₂",
                            fmtG(bd?.actual_co2e_g ?? cd.actual_cost_gco2e),
                          ],
                          [
                            "Carbon Saved",
                            fmtG(bd?.carbon_saved_g ?? cd.carbon_saved_grams),
                          ],
                          [
                            "Reduction",
                            `${Number(bd?.reduction_percent ?? cd.efficiency_percent ?? 0).toFixed(1)}%`,
                          ],
                          ["Region", String(zone || "—")],
                          ["Last Updated", String(updated || "—")],
                        ]
                        return (
                          <>
                            <div className="grid grid-cols-2 gap-3">
                              <div className="rounded-lg border border-border/40 px-3 py-2">
                                <div className="flex items-center gap-1.5 mb-1">
                                  <Leaf className="w-3.5 h-3.5 text-green-400" />
                                  <span className="text-xs text-muted-foreground">
                                    Carbon Saved
                                  </span>
                                </div>
                                <p className="text-xl font-bold tabular-nums">
                                  {fmtG(cd.carbon_saved_grams)}
                                </p>
                              </div>
                              <div className="rounded-lg border border-border/40 px-3 py-2">
                                <div className="flex items-center gap-1.5 mb-1">
                                  <Zap className="w-3.5 h-3.5 text-blue-400" />
                                  <span className="text-xs text-muted-foreground">
                                    Reduction
                                  </span>
                                </div>
                                <p className="text-xl font-bold tabular-nums">
                                  {Number(cd.efficiency_percent ?? 0).toFixed(1)}%
                                </p>
                              </div>
                              <div className="rounded-lg border border-border/40 px-3 py-2">
                                <div className="flex items-center gap-1.5 mb-1">
                                  <Star className="w-3.5 h-3.5 text-amber-400" />
                                  <span className="text-xs text-muted-foreground">
                                    Baseline CO₂
                                  </span>
                                </div>
                                <p className="text-lg font-semibold tabular-nums">
                                  {fmtG(cd.baseline_cost_gco2e)}
                                </p>
                              </div>
                              <div className="rounded-lg border border-border/40 px-3 py-2">
                                <div className="flex items-center gap-1.5 mb-1">
                                  <Leaf className="w-3.5 h-3.5 text-emerald-400" />
                                  <span className="text-xs text-muted-foreground">
                                    Actual CO₂
                                  </span>
                                </div>
                                <p className="text-lg font-semibold tabular-nums">
                                  {fmtG(cd.actual_cost_gco2e)}
                                </p>
                              </div>
                            </div>

                            <div className="space-y-1.5 pt-1">
                              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                                Energy → grid → CO₂e
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

                            {(cd.methodology || result.methodology) && (
                              <div className="rounded-lg border border-border/40 bg-muted/20 px-3 py-2.5 space-y-1.5">
                                <div className="flex items-center gap-1.5">
                                  <Info className="w-3.5 h-3.5 text-muted-foreground" />
                                  <p className="text-xs font-medium text-muted-foreground">
                                    Methodology
                                  </p>
                                </div>
                                <p className="text-xs text-muted-foreground leading-relaxed">
                                  {cd.methodology || result.methodology}
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
                  <ProcessingInsightsPanel insights={result?.processing_insights} />
                ) : null}
              </motion.div>

              <motion.div
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.2 }}
                className="lg:col-span-2"
              >
                {showLiveFeed ? (
                  <LiveFeed logs={logs} />
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
