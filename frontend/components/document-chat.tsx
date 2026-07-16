"use client"

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react"
import { motion, AnimatePresence } from "framer-motion"
import {
  CheckCircle2,
  Copy,
  FileText,
  Layers,
  Loader2,
  MessageSquarePlus,
  PanelRightClose,
  PanelRightOpen,
  Quote,
  RefreshCw,
  Send,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { apiFetch } from "@/lib/api"
import { MarkdownContent } from "@/components/markdown-content"
import {
  AnswerSources,
  type RetrievedChunkMeta,
} from "@/components/answer-sources"
import { DeveloperDetails } from "@/components/developer-details"
import {
  QueryPerformancePanel,
  type FrontendTiming,
  type LatencyPayload,
} from "@/components/query-performance-panel"
import {
  extractCompactMetrics,
  fmtG,
  fmtPct,
  type CompactJobMetrics,
} from "@/lib/job-results-metrics"
import { useFinalizedMetrics } from "@/hooks/use-finalized-metrics"
import {
  revisionOf,
  type FinalizedJobResult,
} from "@/lib/finalized-metrics-store"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { MAX_QUERY_CHARS, sanitizeQuery } from "@/lib/input-validation"

const SUGGESTIONS = [
  "Summarize this document in one paragraph",
  "What are the key findings?",
  "Explain this like I'm a beginner",
  "Extract important numbers",
  "List all recommendations",
  "Compare sections 2 and 4",
  "Find risks and limitations",
  "Generate interview questions",
] as const

const PIPELINE_STEPS = [
  "Document Indexed",
  "OCR Completed",
  "Headings Parsed",
  "Tables Extracted",
  "Images Analyzed",
  "Embeddings Generated",
  "RAG Ready",
] as const

type ChatRole = "user" | "assistant"

type ChatMessage = {
  id: string
  role: ChatRole
  content: string
  createdAt: number
  streaming?: boolean
  feedback?: "up" | "down" | null
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
    latency?: LatencyPayload | null
    frontend_timing?: FrontendTiming | null
  }
}

type JobLike = {
  document_id: string
  filename?: string
  carbon_data?: Record<string, unknown> | null
  processing_insights?: Record<string, unknown> | null
  final_summary?: string
  comparison_models?: unknown
  our_system?: unknown
  summary_cards?: unknown
  chart_bars?: unknown
  methodology?: string | null
}

const CHAT_STORAGE_VERSION = 1

function chatStorageKey(documentId: string) {
  return `green-rag-chat:v${CHAT_STORAGE_VERSION}:${documentId}`
}

function loadPersistedChat(documentId: string): ChatMessage[] {
  if (typeof window === "undefined" || !documentId) return []
  try {
    const raw = localStorage.getItem(chatStorageKey(documentId))
    if (!raw) return []
    const parsed = JSON.parse(raw) as { messages?: ChatMessage[] }
    if (!Array.isArray(parsed?.messages)) return []
    return parsed.messages
      .filter(
        (m) =>
          m &&
          (m.role === "user" || m.role === "assistant") &&
          typeof m.content === "string" &&
          typeof m.id === "string",
      )
      .map((m) => ({
        ...m,
        streaming: false,
        createdAt: typeof m.createdAt === "number" ? m.createdAt : Date.now(),
      }))
  } catch {
    return []
  }
}

function persistChat(documentId: string, messages: ChatMessage[]) {
  if (typeof window === "undefined" || !documentId) return
  try {
    const toSave = messages
      .filter((m) => m.content || m.role === "user")
      .map((m) => ({
        ...m,
        streaming: false,
      }))
    if (toSave.length === 0) {
      localStorage.removeItem(chatStorageKey(documentId))
      return
    }
    localStorage.setItem(
      chatStorageKey(documentId),
      JSON.stringify({
        version: CHAT_STORAGE_VERSION,
        savedAt: Date.now(),
        messages: toSave,
      }),
    )
  } catch {
    // Quota / private mode — ignore
  }
}

function clearPersistedChat(documentId: string) {
  if (typeof window === "undefined" || !documentId) return
  try {
    localStorage.removeItem(chatStorageKey(documentId))
  } catch {
    // ignore
  }
}

function uid() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
}

function formatTime(ts: number) {
  try {
    return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
  } catch {
    return ""
  }
}

function friendlyStrategy(m: CompactJobMetrics): string {
  const id =
    (m.strategy?.strategy_id as string) ||
    (m.strategy?.map_mode as string) ||
    ""
  if (!id) return "Adaptive"
  return id
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

function estimatePages(m: CompactJobMetrics): number | null {
  const fromProfile = Number(m.documentProfile?.pages_estimate)
  if (Number.isFinite(fromProfile) && fromProfile > 0) return Math.round(fromProfile)
  const fromDiag = Number(
    (m.structureDiagnostics as { pages?: number } | null)?.pages,
  )
  if (Number.isFinite(fromDiag) && fromDiag > 0) return Math.round(fromDiag)
  if (m.tokens.input > 0) return Math.max(1, Math.ceil(m.tokens.input / 500))
  return null
}

function embeddingModelLabel(m: CompactJobMetrics): string {
  const fromStrategy =
    (m.strategy?.embedding_model as string) ||
    (m.documentProfile?.embedding_model as string)
  if (typeof fromStrategy === "string" && fromStrategy.trim()) return fromStrategy
  return "text-embedding-3-large"
}

function retrievalLabel(insights: Record<string, unknown> | null | undefined): string {
  const raw = insights?.retrieval_strategy
  if (typeof raw === "string" && raw.trim()) return raw
  return "Hybrid dense + sparse"
}

function avgChunkScore(chunks: RetrievedChunkMeta[] | null | undefined): number | null {
  if (!chunks?.length) return null
  const scores = chunks.map((c) => Number(c.score)).filter((n) => Number.isFinite(n))
  if (!scores.length) return null
  return scores.reduce((a, b) => a + b, 0) / scores.length
}

function Chip({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border border-border/50 bg-muted/30 px-2.5 py-1 text-[11px] text-muted-foreground",
        className,
      )}
    >
      {children}
    </span>
  )
}

function EmptyState({
  filename,
  metrics,
  insights,
  onSuggest,
}: {
  filename: string
  metrics: CompactJobMetrics
  insights: Record<string, unknown> | null
  onSuggest: (prompt: string) => void
}) {
  const pages = estimatePages(metrics)
  const strategy = friendlyStrategy(metrics)
  const embedding = embeddingModelLabel(metrics)
  const retrieval = retrievalLabel(insights)
  const quality =
    metrics.accuracyEstimate != null
      ? metrics.accuracyEstimate <= 1
        ? metrics.accuracyEstimate * 100
        : metrics.accuracyEstimate
      : metrics.confidence != null
        ? metrics.confidence <= 1
          ? metrics.confidence * 100
          : metrics.confidence
        : null

  const totalLatencySec =
    metrics.timeline.length > 0
      ? metrics.timeline.reduce((s, t) => s + (Number(t.duration_ms) || 0), 0) / 1000
      : null

  return (
    <div className="mx-auto w-full max-w-3xl space-y-5 py-2">
      <div className="rounded-xl border border-border/50 bg-card/60 p-4 sm:p-5">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-emerald-500/15 border border-emerald-500/25">
            <CheckCircle2 className="h-4 w-4 text-emerald-400" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-foreground">Document ready</p>
            <p className="mt-0.5 truncate text-xs text-muted-foreground" title={filename}>
              {filename || "Document"} indexed and queryable
            </p>
          </div>
        </div>

        <ul className="mt-4 grid grid-cols-1 gap-1.5 sm:grid-cols-2">
          {PIPELINE_STEPS.map((step) => (
            <li
              key={step}
              className="flex items-center gap-2 rounded-md px-1.5 py-1 text-xs text-muted-foreground"
            >
              <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-400" />
              <span>{step}</span>
            </li>
          ))}
        </ul>

        <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3">
          {[
            ["Pages", pages != null ? String(pages) : "—"],
            ["Strategy", strategy],
            ["Chunks", String(metrics.totalChunks || "—")],
            ["Embedding", embedding],
            ["Retrieval", retrieval],
            [
              "Est. quality",
              quality != null ? `${Math.round(quality)}%` : "—",
            ],
            ["Carbon used", fmtG(metrics.optimizedG)],
            [
              "Carbon saved",
              metrics.emissionsIncreased
                ? fmtG(Math.abs(metrics.savedG))
                : fmtPct(metrics.reductionPct),
            ],
            [
              "Latency",
              totalLatencySec != null ? `${totalLatencySec.toFixed(1)} s` : "—",
            ],
          ].map(([label, value]) => (
            <div
              key={label}
              className="rounded-lg border border-border/40 bg-muted/20 px-2.5 py-2 min-w-0"
            >
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
                {label}
              </p>
              <p className="mt-0.5 truncate text-xs font-medium text-foreground" title={value}>
                {value}
              </p>
            </div>
          ))}
        </div>
      </div>

      <div>
        <div className="mb-2.5 flex items-center gap-2 text-xs text-muted-foreground">
          <Sparkles className="h-3.5 w-3.5 text-emerald-400" />
          <span>Try asking…</span>
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {SUGGESTIONS.map((prompt) => (
            <button
              key={prompt}
              type="button"
              onClick={() => onSuggest(prompt)}
              className={cn(
                "rounded-xl border border-border/50 bg-card/40 px-3.5 py-3 text-left text-sm",
                "text-foreground/90 transition-colors hover:border-emerald-500/35 hover:bg-emerald-500/5",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              )}
            >
              {prompt}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

function MessageActions({
  content,
  onCopy,
  onRegenerate,
  onCite,
  feedback,
  onFeedback,
}: {
  content: string
  onCopy: () => void
  onRegenerate?: () => void
  onCite?: () => void
  feedback?: "up" | "down" | null
  onFeedback?: (v: "up" | "down") => void
}) {
  return (
    <div className="mt-2 flex flex-wrap items-center gap-0.5">
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            onClick={onCopy}
            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted/50 hover:text-foreground"
            aria-label="Copy"
          >
            <Copy className="h-3.5 w-3.5" />
          </button>
        </TooltipTrigger>
        <TooltipContent>Copy</TooltipContent>
      </Tooltip>
      {onRegenerate ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              onClick={onRegenerate}
              className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted/50 hover:text-foreground"
              aria-label="Regenerate"
            >
              <RefreshCw className="h-3.5 w-3.5" />
            </button>
          </TooltipTrigger>
          <TooltipContent>Regenerate</TooltipContent>
        </Tooltip>
      ) : null}
      {onCite ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              onClick={onCite}
              className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted/50 hover:text-foreground"
              aria-label="Citations"
            >
              <Quote className="h-3.5 w-3.5" />
            </button>
          </TooltipTrigger>
          <TooltipContent>Citations</TooltipContent>
        </Tooltip>
      ) : null}
      {onFeedback ? (
        <>
          <button
            type="button"
            onClick={() => onFeedback("up")}
            className={cn(
              "inline-flex h-7 w-7 items-center justify-center rounded-md hover:bg-muted/50",
              feedback === "up" ? "text-emerald-400" : "text-muted-foreground hover:text-foreground",
            )}
            aria-label="Thumbs up"
          >
            <ThumbsUp className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={() => onFeedback("down")}
            className={cn(
              "inline-flex h-7 w-7 items-center justify-center rounded-md hover:bg-muted/50",
              feedback === "down" ? "text-rose-400" : "text-muted-foreground hover:text-foreground",
            )}
            aria-label="Thumbs down"
          >
            <ThumbsDown className="h-3.5 w-3.5" />
          </button>
        </>
      ) : null}
      <span className="sr-only">{content.slice(0, 20)}</span>
    </div>
  )
}

function InsightsPanel({
  open,
  onClose,
  latest,
  carbonSavedGrams,
}: {
  open: boolean
  onClose: () => void
  latest: ChatMessage | null
  carbonSavedGrams?: number | null
}) {
  const chunks = latest?.meta?.retrieved_chunks || []
  const avg = avgChunkScore(chunks)
  const stages = latest?.meta?.latency?.stages_ms || {}

  return (
    <aside
      className={cn(
        "hidden shrink-0 flex-col border-l border-border/50 bg-card/30 transition-all duration-300 ease-in-out xl:flex",
        open ? "w-[320px] opacity-100" : "w-0 opacity-0 overflow-hidden border-0",
      )}
    >
      {open ? (
        <div className="flex h-full flex-col overflow-hidden">
          <div className="flex items-center justify-between border-b border-border/40 px-3 py-2.5">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Insights
            </p>
            <button
              type="button"
              onClick={onClose}
              className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted/40"
              aria-label="Close insights"
            >
              <PanelRightClose className="h-3.5 w-3.5" />
            </button>
          </div>
          <div className="flex-1 space-y-4 overflow-y-auto p-3">
            <QueryPerformancePanel
              latency={latest?.meta?.latency}
              frontend={latest?.meta?.frontend_timing}
            />

            {!latest?.meta ? (
              <p className="text-xs text-muted-foreground leading-relaxed">
                Ask a question to see retrieved chunks, confidence, and latency for each answer.
              </p>
            ) : (
              <>
                <div className="grid grid-cols-2 gap-2">
                  <div className="rounded-lg border border-border/40 bg-muted/20 px-2.5 py-2">
                    <p className="text-[10px] text-muted-foreground">Confidence</p>
                    <p className="text-sm font-semibold tabular-nums">
                      {latest.meta.confidence != null
                        ? `${Math.round(latest.meta.confidence * 100)}%`
                        : "—"}
                    </p>
                  </div>
                  <div className="rounded-lg border border-border/40 bg-muted/20 px-2.5 py-2">
                    <p className="text-[10px] text-muted-foreground">Client RTT</p>
                    <p className="text-sm font-semibold tabular-nums">
                      {latest.meta.latency_ms != null
                        ? `${(latest.meta.latency_ms / 1000).toFixed(1)} s`
                        : "—"}
                    </p>
                  </div>
                  <div className="rounded-lg border border-border/40 bg-muted/20 px-2.5 py-2">
                    <p className="text-[10px] text-muted-foreground">Backend</p>
                    <p className="text-sm font-semibold tabular-nums">
                      {stages.total_ms != null
                        ? `${(Number(stages.total_ms) / 1000).toFixed(1)} s`
                        : "—"}
                    </p>
                  </div>
                  <div className="rounded-lg border border-border/40 bg-muted/20 px-2.5 py-2">
                    <p className="text-[10px] text-muted-foreground">Chunks</p>
                    <p className="text-sm font-semibold tabular-nums">
                      {chunks.length || latest.meta.sources?.length || 0}
                    </p>
                  </div>
                  <div className="rounded-lg border border-border/40 bg-muted/20 px-2.5 py-2">
                    <p className="text-[10px] text-muted-foreground">Relevance</p>
                    <p className="text-sm font-semibold tabular-nums">
                      {avg != null ? avg.toFixed(2) : "—"}
                    </p>
                  </div>
                  <div className="rounded-lg border border-border/40 bg-muted/20 px-2.5 py-2">
                    <p className="text-[10px] text-muted-foreground">TTFT</p>
                    <p className="text-sm font-semibold tabular-nums">
                      {latest.meta.frontend_timing?.perceived_ttft_ms != null
                        ? `${(Number(latest.meta.frontend_timing.perceived_ttft_ms) / 1000).toFixed(2)} s`
                        : stages.llm_ttft_ms != null
                          ? `${(Number(stages.llm_ttft_ms) / 1000).toFixed(2)} s`
                          : "—"}
                    </p>
                  </div>
                  <div className="rounded-lg border border-border/40 bg-muted/20 px-2.5 py-2">
                    <p className="text-[10px] text-muted-foreground">Tokens/sec</p>
                    <p className="text-sm font-semibold tabular-nums">
                      {(() => {
                        const fe = latest.meta.frontend_timing?.tokens_per_sec
                        const nim = (latest.meta.latency?.meta as { nim?: { tokens_per_sec?: number } } | undefined)?.nim
                          ?.tokens_per_sec
                        const v = fe ?? nim
                        return v != null && Number(v) > 0 ? Number(v).toFixed(1) : "—"
                      })()}
                    </p>
                  </div>
                </div>

                {latest.meta.model_used ? (
                  <div>
                    <p className="mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                      Model
                    </p>
                    <p className="text-xs font-medium break-all">{latest.meta.model_used}</p>
                  </div>
                ) : null}

                {carbonSavedGrams != null ? (
                  <div>
                    <p className="mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                      Job carbon saved
                    </p>
                    <p className="text-xs font-medium">{fmtG(Number(carbonSavedGrams))}</p>
                  </div>
                ) : null}

                <div>
                  <p className="mb-2 text-[10px] uppercase tracking-wide text-muted-foreground">
                    Retrieved chunks
                  </p>
                  {chunks.length === 0 ? (
                    <p className="text-xs text-muted-foreground">No chunk metadata returned.</p>
                  ) : (
                    <ul className="space-y-2">
                      {chunks.slice(0, 8).map((c, i) => (
                        <li
                          key={`${c.id || i}-${c.citation ?? i}`}
                          className="rounded-lg border border-border/40 bg-muted/15 px-2.5 py-2"
                        >
                          <div className="mb-1 flex items-center justify-between gap-2 text-[10px] text-muted-foreground">
                            <span>#{c.citation ?? i + 1}</span>
                            {c.score != null ? (
                              <span className="tabular-nums">{Number(c.score).toFixed(2)}</span>
                            ) : null}
                          </div>
                          <p className="text-[11px] leading-relaxed text-foreground/85 line-clamp-4">
                            {(c.preview || c.parent_section || "—").trim()}
                          </p>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      ) : null}
    </aside>
  )
}

type Props = {
  result: JobLike
}

/**
 * Premium document RAG chat — empty-state showcase + composer + live insights.
 */
export function DocumentChat({ result }: Props) {
  const jobId = String((result as { job_id?: string }).job_id || "")
  const shared = useFinalizedMetrics({ refreshOnMount: false })
  const metrics = useMemo(() => {
    if (
      jobId &&
      shared.jobId === jobId &&
      shared.metrics &&
      shared.revision >= revisionOf(result as FinalizedJobResult)
    ) {
      return shared.metrics
    }
    return extractCompactMetrics(result as Parameters<typeof extractCompactMetrics>[0])
  }, [result, jobId, shared.jobId, shared.metrics, shared.revision])
  const insights = (result.processing_insights || null) as Record<string, unknown> | null
  const documentId = result.document_id

  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [hydrated, setHydrated] = useState(false)
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [insightsOpen, setInsightsOpen] = useState(true)
  const [citeFocusId, setCiteFocusId] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const streamTimer = useRef<ReturnType<typeof setInterval> | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const hasUserMessages = messages.some((m) => m.role === "user")
  const latestAssistant = [...messages].reverse().find((m) => m.role === "assistant" && m.meta) || null
  const lastRetrieved =
    latestAssistant?.meta?.retrieved_chunks?.length ??
    latestAssistant?.meta?.sources?.length ??
    0

  // Restore per-document chat on mount / document switch
  useEffect(() => {
    setHydrated(false)
    abortRef.current?.abort()
    setLoading(false)
    setInput("")
    setCiteFocusId(null)
    setMessages(loadPersistedChat(documentId))
    setHydrated(true)
  }, [documentId])

  // Persist after hydration (survives refresh + returning to this document)
  useEffect(() => {
    if (!hydrated || !documentId) return
    if (loading || messages.some((m) => m.streaming)) return
    persistChat(documentId, messages)
  }, [messages, documentId, hydrated, loading])

  useEffect(() => {
    return () => {
      if (streamTimer.current) clearInterval(streamTimer.current)
      abortRef.current?.abort()
    }
  }, [])

  useEffect(() => {
    if (!hasUserMessages) return
    const el = scrollRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [messages, loading, hasUserMessages])

  const resizeTextarea = useCallback(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = "auto"
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`
  }, [])

  useEffect(() => {
    resizeTextarea()
  }, [input, resizeTextarea])

  const startNewChat = useCallback(() => {
    abortRef.current?.abort()
    setLoading(false)
    setMessages([])
    setInput("")
    setCiteFocusId(null)
    clearPersistedChat(documentId)
  }, [documentId])

  const runAssistant = useCallback(
    async (query: string, assistantId: string) => {
      const startedAt = performance.now()
      let perceivedTtft: number | null = null
      abortRef.current?.abort()
      const ac = new AbortController()
      abortRef.current = ac

      try {
        const response = await apiFetch("/rag-query/stream", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Accept: "text/event-stream",
          },
          body: JSON.stringify({
            document_id: result.document_id,
            query,
          }),
          signal: ac.signal,
        })

        if (!response.ok || !response.body) {
          // Fallback to blocking JSON if stream unavailable
          const fallback = await apiFetch("/rag-query", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              document_id: result.document_id,
              query,
            }),
          })
          const latencyMs = Math.round(performance.now() - startedAt)
          if (!fallback.ok) {
            throw new Error(`HTTP ${fallback.status}`)
          }
          const data = await fallback.json()
          const latencyPayload = (data.latency || null) as LatencyPayload | null
          const prompt = (latencyPayload?.meta as { prompt?: { tokens_per_sec?: number } } | undefined)?.prompt
          const nim = (latencyPayload?.meta as { nim?: { tokens_per_sec?: number } } | undefined)?.nim
          const tokPerSec = Number(nim?.tokens_per_sec || prompt?.tokens_per_sec) || null
          const meta: ChatMessage["meta"] = {
            confidence: data.confidence,
            reasoning_path: data.reasoning_path,
            model_used: data.model_used,
            entities_used: data.entities_used,
            missing_context: data.missing_context,
            sources: Array.isArray(data.sources) ? data.sources : [],
            retrieved_chunks: Array.isArray(data.retrieved_chunks) ? data.retrieved_chunks : [],
            knowledge_sources: data.knowledge_sources,
            skill: data.skill,
            latency_ms: latencyMs,
            latency: latencyPayload,
            frontend_timing: {
              client_wall_ms: latencyMs,
              ttfb_ms: null,
              perceived_ttft_ms: null,
              tokens_per_sec: tokPerSec,
            },
          }
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? { ...m, content: data.answer || "No answer returned.", streaming: false, meta }
                : m,
            ),
          )
          return
        }

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ""
        let assembled = ""

        // Coalesce tiny NIM deltas into short word-ish chunks (smoother UI, fewer re-renders).
        // First paint stays immediate so perceived TTFT is unchanged.
        const FLUSH_MS = 40
        const MIN_CHARS = 12
        let pending = ""
        let flushTimer: ReturnType<typeof setTimeout> | null = null
        let paintedOnce = false

        const paint = () => {
          if (flushTimer != null) {
            clearTimeout(flushTimer)
            flushTimer = null
          }
          if (!pending && paintedOnce) return
          assembled += pending
          pending = ""
          paintedOnce = true
          const snapshot = assembled
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? { ...m, content: snapshot, streaming: true }
                : m,
            ),
          )
        }

        const shouldFlushSoon = (chunk: string) => {
          if (chunk.length >= MIN_CHARS) return true
          // Prefer flushing on word / punctuation boundaries
          return /[\s.,;:!?)\]}\n]$/.test(chunk)
        }

        const applyToken = (delta: string) => {
          if (!delta) return
          if (perceivedTtft == null) {
            perceivedTtft = Math.round(performance.now() - startedAt)
          }
          pending += delta

          // First visible paint: no delay (preserves perceived TTFT)
          if (!paintedOnce) {
            paint()
            return
          }

          if (shouldFlushSoon(pending)) {
            paint()
            return
          }

          if (flushTimer == null) {
            flushTimer = setTimeout(paint, FLUSH_MS)
          }
        }

        const flushPending = () => {
          if (flushTimer != null) {
            clearTimeout(flushTimer)
            flushTimer = null
          }
          if (pending) paint()
        }

        const finishWithDone = (data: Record<string, unknown>) => {
          flushPending()
          const latencyMs = Math.round(performance.now() - startedAt)
          const latencyPayload = (data.latency || null) as LatencyPayload | null
          const prompt = (latencyPayload?.meta as { prompt?: { tokens_per_sec?: number } } | undefined)?.prompt
          const nim = (latencyPayload?.meta as { nim?: { tokens_per_sec?: number } } | undefined)?.nim
          const tokPerSec = Number(nim?.tokens_per_sec || prompt?.tokens_per_sec) || null
          const finalAnswer =
            (typeof data.answer === "string" && data.answer) || assembled || "No answer returned."
          const meta: ChatMessage["meta"] = {
            confidence: data.confidence as number | undefined,
            reasoning_path: data.reasoning_path as string[] | undefined,
            model_used: (data.model_used as string) || null,
            entities_used: data.entities_used as string[] | undefined,
            missing_context: data.missing_context as string[] | undefined,
            sources: Array.isArray(data.sources) ? (data.sources as string[]) : [],
            retrieved_chunks: Array.isArray(data.retrieved_chunks)
              ? (data.retrieved_chunks as RetrievedChunkMeta[])
              : [],
            knowledge_sources: data.knowledge_sources as string[] | undefined,
            skill: (data.skill as string) || null,
            latency_ms: latencyMs,
            latency: latencyPayload,
            frontend_timing: {
              client_wall_ms: latencyMs,
              ttfb_ms:
                typeof data.client_ttft_ms === "number"
                  ? data.client_ttft_ms
                  : perceivedTtft,
              perceived_ttft_ms: perceivedTtft,
              tokens_per_sec: tokPerSec,
            },
          }
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? { ...m, content: finalAnswer, streaming: false, meta }
                : m,
            ),
          )
        }

        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const parts = buffer.split("\n\n")
          buffer = parts.pop() || ""
          for (const part of parts) {
            const line = part
              .split("\n")
              .map((l) => l.trim())
              .find((l) => l.startsWith("data:"))
            if (!line) continue
            const raw = line.slice(5).trim()
            if (!raw || raw === "[DONE]") continue
            let evt: Record<string, unknown>
            try {
              evt = JSON.parse(raw) as Record<string, unknown>
            } catch {
              continue
            }
            const event = evt.event
            if (event === "token") {
              applyToken(String(evt.text || ""))
            } else if (event === "done") {
              finishWithDone(evt)
            } else if (event === "error") {
              flushPending()
              throw new Error(String(evt.message || "Stream error"))
            }
          }
        }

        flushPending()

        // If stream ended without a done event, finalize with assembled text
        setMessages((prev) => {
          const cur = prev.find((m) => m.id === assistantId)
          if (cur && cur.streaming) {
            return prev.map((m) =>
              m.id === assistantId
                ? {
                    ...m,
                    content: assembled || m.content || "No answer returned.",
                    streaming: false,
                    meta: {
                      ...m.meta,
                      latency_ms: Math.round(performance.now() - startedAt),
                      frontend_timing: {
                        client_wall_ms: Math.round(performance.now() - startedAt),
                        ttfb_ms: perceivedTtft,
                        perceived_ttft_ms: perceivedTtft,
                        tokens_per_sec: null,
                      },
                    },
                  }
                : m,
            )
          }
          return prev
        })
      } catch (err) {
        if ((err as { name?: string })?.name === "AbortError") return
        console.error("Chat error:", err)
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? {
                  ...m,
                  content: "Network error. Please try again.",
                  streaming: false,
                }
              : m,
          ),
        )
      } finally {
        setLoading(false)
      }
    },
    [result.document_id],
  )

  const sendQuery = useCallback(
    async (raw: string) => {
      if (loading) return
      let query: string
      try {
        query = sanitizeQuery(raw)
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Invalid query"
        setMessages((prev) => [
          ...prev,
          {
            id: uid(),
            role: "assistant",
            content: msg,
            createdAt: Date.now(),
          },
        ])
        return
      }

      const userMsg: ChatMessage = {
        id: uid(),
        role: "user",
        content: query,
        createdAt: Date.now(),
      }
      const assistantId = uid()
      setMessages((prev) => [
        ...prev,
        userMsg,
        {
          id: assistantId,
          role: "assistant",
          content: "",
          createdAt: Date.now(),
          streaming: true,
        },
      ])
      setInput("")
      setLoading(true)
      await runAssistant(query, assistantId)
    },
    [loading, runAssistant],
  )

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    void sendQuery(input)
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      void sendQuery(input)
    }
  }

  const regenerateLast = () => {
    if (loading) return
    const lastUser = [...messages].reverse().find((m) => m.role === "user")
    if (!lastUser) return
    const lastUserIdx = [...messages]
      .map((m) => m.id)
      .lastIndexOf(lastUser.id)
    const assistantId = uid()
    setMessages((prev) => [
      ...prev.slice(0, lastUserIdx + 1),
      {
        id: assistantId,
        role: "assistant",
        content: "",
        createdAt: Date.now(),
        streaming: true,
      },
    ])
    setLoading(true)
    void runAssistant(lastUser.content, assistantId)
  }

  const carbonSaved = Number(
    (result.carbon_data as { carbon_saved_grams?: number } | null)?.carbon_saved_grams,
  )

  return (
    <div className="flex min-h-[520px] max-h-[min(78vh,760px)] overflow-hidden rounded-xl border border-border/50 bg-card/40">
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Context chips */}
        <div className="flex flex-wrap items-center gap-1.5 border-b border-border/40 px-3 py-2.5 sm:px-4">
          <Chip className="max-w-[180px] sm:max-w-[240px]">
            <FileText className="h-3 w-3 shrink-0 text-emerald-400" />
            <span className="truncate">{result.filename || "Document"}</span>
          </Chip>
          <Chip>
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
            Retrieval ready
          </Chip>
          <Chip>
            <Layers className="h-3 w-3 shrink-0" />
            {metrics.totalChunks || "—"} chunks indexed
          </Chip>
          {hasUserMessages ? (
            <Chip>
              {lastRetrieved} retrieved
            </Chip>
          ) : null}
          <Chip>
            Context · ~{Math.min(100, Math.round((metrics.tokens.retrieved || 0) / 80) || 12)}%
          </Chip>
          <div className="ml-auto flex items-center gap-1">
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <button
                  type="button"
                  disabled={!hasUserMessages && !input.trim()}
                  className="inline-flex h-7 items-center gap-1 rounded-md px-2 text-[11px] text-muted-foreground hover:bg-muted/40 hover:text-foreground disabled:pointer-events-none disabled:opacity-40"
                >
                  <MessageSquarePlus className="h-3.5 w-3.5" />
                  New chat
                </button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Start a new chat?</AlertDialogTitle>
                  <AlertDialogDescription>
                    The current chat will be discarded. This cannot be undone.
                    Refreshing the page keeps your current chat; only New chat
                    clears it for this document.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Keep chatting</AlertDialogCancel>
                  <AlertDialogAction onClick={startNewChat}>
                    Discard and start new
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
            <button
              type="button"
              className="hidden xl:inline-flex h-7 items-center gap-1 rounded-md px-2 text-[11px] text-muted-foreground hover:bg-muted/40 hover:text-foreground"
              onClick={() => setInsightsOpen((v) => !v)}
            >
              {insightsOpen ? (
                <PanelRightClose className="h-3.5 w-3.5" />
              ) : (
                <PanelRightOpen className="h-3.5 w-3.5" />
              )}
              Insights
            </button>
          </div>
        </div>

        {/* Messages / empty */}
        <div
          ref={scrollRef}
          className={cn(
            "flex-1 overflow-y-auto px-3 py-4 sm:px-5",
            !hasUserMessages && "flex flex-col justify-center",
          )}
        >
          {!hasUserMessages ? (
            <EmptyState
              filename={result.filename || "Document"}
              metrics={metrics}
              insights={insights}
              onSuggest={(prompt) => void sendQuery(prompt)}
            />
          ) : (
            <div className="mx-auto w-full max-w-3xl space-y-4">
              <AnimatePresence initial={false}>
                {messages.map((msg) => (
                  <motion.div
                    key={msg.id}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.22, ease: "easeOut" }}
                    className={cn(
                      "flex",
                      msg.role === "user" ? "justify-end" : "justify-start",
                    )}
                  >
                    <div
                      className={cn(
                        "min-w-0 space-y-1",
                        msg.role === "user" ? "max-w-[85%]" : "max-w-[95%] w-full",
                      )}
                    >
                      <div className="flex items-center gap-2 px-1">
                        <span className="text-[10px] text-muted-foreground">
                          {msg.role === "user" ? "You" : "Assistant"}
                        </span>
                        <span className="text-[10px] text-muted-foreground/70">
                          {formatTime(msg.createdAt)}
                        </span>
                      </div>
                      <div
                        className={cn(
                          "rounded-2xl px-3.5 py-2.5 sm:px-4 sm:py-3",
                          msg.role === "user"
                            ? "bg-zinc-100 text-zinc-900"
                            : "border border-border/50 bg-muted/40",
                        )}
                      >
                        {msg.role === "user" ? (
                          <p className="text-sm whitespace-pre-wrap leading-relaxed">
                            {msg.content}
                          </p>
                        ) : msg.content ? (
                          <>
                            <MarkdownContent content={msg.content} compact />
                            {msg.streaming ? (
                              <span className="ml-0.5 inline-block h-3.5 w-1 animate-pulse bg-emerald-400/80 align-middle" />
                            ) : null}
                          </>
                        ) : (
                          <div className="flex items-center gap-2 text-sm text-muted-foreground">
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            Thinking…
                          </div>
                        )}
                      </div>

                      {msg.role === "assistant" && msg.content && !msg.streaming ? (
                        <>
                          <MessageActions
                            content={msg.content}
                            onCopy={() => navigator.clipboard.writeText(msg.content)}
                            onRegenerate={
                              msg.id === messages[messages.length - 1]?.id
                                ? regenerateLast
                                : undefined
                            }
                            onCite={
                              msg.meta?.retrieved_chunks?.length || msg.meta?.sources?.length
                                ? () => {
                                    setCiteFocusId(msg.id)
                                    setInsightsOpen(true)
                                  }
                                : undefined
                            }
                            feedback={msg.feedback}
                            onFeedback={(v) =>
                              setMessages((prev) =>
                                prev.map((m) =>
                                  m.id === msg.id
                                    ? { ...m, feedback: m.feedback === v ? null : v }
                                    : m,
                                ),
                              )
                            }
                          />
                          {msg.meta && citeFocusId === msg.id ? (
                            <div className="mt-2 rounded-xl border border-border/40 bg-muted/20 p-3">
                              <AnswerSources
                                sources={msg.meta.sources}
                                retrievedChunks={msg.meta.retrieved_chunks}
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
                            </div>
                          ) : null}
                        </>
                      ) : null}
                    </div>
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>
          )}
        </div>

        {/* Composer */}
        <div className="border-t border-border/40 px-3 py-3 sm:px-4">
          <form onSubmit={onSubmit} className="mx-auto w-full max-w-3xl">
            <div className="relative rounded-2xl border border-border/60 bg-background/80 focus-within:border-emerald-500/40 transition-colors">
              <textarea
                ref={textareaRef}
                rows={1}
                value={input}
                onChange={(e) => setInput(e.target.value.slice(0, MAX_QUERY_CHARS))}
                onKeyDown={onKeyDown}
                placeholder="Ask anything about your document..."
                disabled={loading}
                maxLength={MAX_QUERY_CHARS}
                className="w-full resize-none bg-transparent px-4 py-3 pr-12 text-sm leading-relaxed placeholder:text-muted-foreground focus:outline-none disabled:opacity-60"
              />
              <button
                type="submit"
                disabled={loading || !input.trim()}
                aria-label="Send"
                className={cn(
                  "absolute bottom-2.5 right-2.5 inline-flex h-8 w-8 items-center justify-center rounded-xl",
                  "bg-emerald-500/90 text-zinc-950 transition-opacity",
                  "hover:bg-emerald-400 disabled:opacity-40",
                )}
              >
                {loading ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Send className="h-3.5 w-3.5" />
                )}
              </button>
            </div>
            <p className="mt-1.5 px-1 text-[10px] text-muted-foreground">
              Enter to send · Shift+Enter for newline
            </p>
          </form>
        </div>
      </div>

      <InsightsPanel
        open={insightsOpen}
        onClose={() => setInsightsOpen(false)}
        latest={latestAssistant}
        carbonSavedGrams={Number.isFinite(carbonSaved) ? carbonSaved : null}
      />
    </div>
  )
}
