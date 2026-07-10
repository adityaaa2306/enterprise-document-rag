"use client"

import { motion } from "framer-motion"
import { useState, useEffect, Suspense } from "react"
import { useSearchParams } from "next/navigation"
import { Sidebar } from "@/components/sidebar"
import { TopBar } from "@/components/top-bar"
import { LiveFeed } from "@/components/live-feed"
import { Card } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Leaf, Zap, Star, Copy, Download } from "lucide-react"
import { Button } from "@/components/ui/button"
import { apiFetch } from "@/lib/api"
import {
  ProcessingInsightsPanel,
  type ProcessingInsightsData,
} from "@/components/processing-insights"

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
}

interface JobResult {
  job_id: string
  document_id: string
  filename: string
  final_summary: string
  carbon_data: CarbonData
  processing_insights?: ProcessingInsightsData | null
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
  const [logs, setLogs] = useState<any[]>([])
  const [result, setResult] = useState<JobResult | null>(null)
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [chatInput, setChatInput] = useState("")
  const [isChatLoading, setIsChatLoading] = useState(false)

  useEffect(() => {
    if (!jobId) return

    let pollInterval: NodeJS.Timeout

    const pollStatus = async () => {
      try {
        const response = await apiFetch(`/job-status/${jobId}`)
        if (response.ok) {
          const data: JobStatus = await response.json()

          setLogs((prev) => {
            const newLog = {
              id: Date.now().toString(),
              timestamp: new Date().toLocaleTimeString(),
              message: data.message,
              type: data.status === "error" ? "error" : "info",
            }
            if (prev.length > 0 && prev[prev.length - 1].message === data.message) return prev
            return [...prev, newLog]
          })

          if (data.status === "complete") {
            setIsComplete(true)
            clearInterval(pollInterval)
            fetchResult()
          } else if (data.status === "error") {
            clearInterval(pollInterval)
            alert(`Job failed: ${data.message}`)
          }
        }
      } catch (error) {
        console.error("Polling error:", error)
      }
    }

    pollInterval = setInterval(pollStatus, 2000)
    pollStatus()

    return () => clearInterval(pollInterval)
  }, [jobId])

  const fetchResult = async () => {
    try {
      const response = await apiFetch(`/job-result/${jobId}`)
      if (response.ok) {
        const data: JobResult = await response.json()
        setResult(data)
        setChatMessages([
          {
            role: "assistant",
            content:
              "Your document is ready! I've read the summary and can now answer your questions.",
          },
        ])
      }
    } catch (error) {
      console.error("Error fetching result:", error)
    }
  }

  const handleCopy = () => {
    if (result?.final_summary) {
      navigator.clipboard.writeText(result.final_summary)
      alert("Summary copied to clipboard!")
    }
  }

  const handleDownload = () => {
    if (result?.final_summary) {
      const blob = new Blob([result.final_summary], { type: "text/plain" })
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = `summary-${result.filename || "document"}.txt`
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

    try {
      const response = await apiFetch("/rag-query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document_id: result.document_id,
          query: userMsg,
        }),
      })

      if (response.ok) {
        const data = await response.json()
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
              sources: data.sources,
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
                <Card className="p-6 bg-gradient-to-br from-card to-card/50 border-border/50 sticky top-20">
                  <h3 className="text-lg font-semibold mb-4">Job Report Card</h3>

                  {result ? (
                    <div className="space-y-4">
                      <div>
                        <p className="text-xs text-muted-foreground mb-1">Job ID</p>
                        <p className="font-mono text-sm">{result.job_id}</p>
                      </div>

                      <div>
                        <p className="text-xs text-muted-foreground mb-1">Routing</p>
                        <p className="font-medium">{preferenceLabel}</p>
                      </div>

                      <div className="space-y-2">
                        <div className="flex items-center gap-2">
                          <Leaf className="w-4 h-4 text-green-400" />
                          <span className="text-sm text-muted-foreground">Carbon Saved</span>
                        </div>
                        <p className="text-2xl font-bold ml-6">
                          {result.carbon_data.carbon_saved_grams?.toFixed(4) || "0.0000"}g CO2e
                        </p>
                      </div>

                      <div className="space-y-2">
                        <div className="flex items-center gap-2">
                          <Star className="w-4 h-4 text-amber-400" />
                          <span className="text-sm text-muted-foreground">Baseline Cost</span>
                        </div>
                        <p className="text-2xl font-bold ml-6">
                          {result.carbon_data.baseline_cost_gco2e?.toFixed(4) || "0.0000"}g CO2e
                        </p>
                      </div>

                      <div className="space-y-2">
                        <div className="flex items-center gap-2">
                          <Zap className="w-4 h-4 text-blue-400" />
                          <span className="text-sm text-muted-foreground">Efficiency</span>
                        </div>
                        <p className="text-2xl font-bold ml-6">
                          {result.carbon_data.efficiency_percent?.toFixed(0) || "0"}%
                        </p>
                      </div>

                      <div>
                        <p className="text-xs text-muted-foreground mb-2">Compute Location</p>
                        <p className="text-sm">{result.carbon_data.compute_location || "Unknown"}</p>
                      </div>
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
                {!isComplete ? (
                  <LiveFeed logs={logs} />
                ) : (
                  <Tabs defaultValue="summary" className="w-full">
                    <TabsList className="grid w-full grid-cols-2">
                      <TabsTrigger value="summary">Summary</TabsTrigger>
                      <TabsTrigger value="chat">Chat (RAG)</TabsTrigger>
                    </TabsList>

                    <TabsContent value="summary" className="space-y-4">
                      <Card className="p-6 bg-card/50 border-border/50">
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
                        <div className="prose prose-invert max-w-none">
                          <div className="text-sm leading-relaxed whitespace-pre-wrap text-foreground">
                            {result?.final_summary}
                          </div>
                        </div>
                      </Card>
                    </TabsContent>

                    <TabsContent value="chat" className="space-y-4">
                      <Card className="p-6 bg-card/50 border-border/50 h-[600px] flex flex-col">
                        <div className="flex-1 overflow-y-auto mb-4 space-y-4 p-2">
                          {chatMessages.map((msg, idx) => (
                            <div
                              key={idx}
                              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                            >
                              <div
                                className={`max-w-[85%] rounded-lg p-3 space-y-2 ${
                                  msg.role === "user"
                                    ? "bg-primary text-primary-foreground"
                                    : "bg-muted"
                                }`}
                              >
                                <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
                                {msg.role === "assistant" && msg.meta ? (
                                  <div className="pt-2 border-t border-border/40 space-y-1.5 text-xs text-muted-foreground">
                                    {msg.meta.model_used ? (
                                      <p>
                                        Model:{" "}
                                        <span className="text-foreground/80">{msg.meta.model_used}</span>
                                      </p>
                                    ) : null}
                                    {msg.meta.confidence != null ? (
                                      <p>
                                        Confidence:{" "}
                                        <span className="text-foreground/80">
                                          {(msg.meta.confidence * 100).toFixed(0)}%
                                        </span>
                                      </p>
                                    ) : null}
                                    {msg.meta.reasoning_path && msg.meta.reasoning_path.length > 0 ? (
                                      <div>
                                        <p className="mb-0.5">Reasoning path</p>
                                        <ul className="list-disc pl-4 space-y-0.5">
                                          {msg.meta.reasoning_path.map((step, i) => (
                                            <li key={i}>{step}</li>
                                          ))}
                                        </ul>
                                      </div>
                                    ) : null}
                                    {msg.meta.entities_used && msg.meta.entities_used.length > 0 ? (
                                      <p>
                                        Entities:{" "}
                                        <span className="text-foreground/80">
                                          {msg.meta.entities_used.join(", ")}
                                        </span>
                                      </p>
                                    ) : null}
                                    {msg.meta.missing_context &&
                                    msg.meta.missing_context.length > 0 ? (
                                      <p className="text-amber-300/90">
                                        Missing context: {msg.meta.missing_context.join("; ")}
                                      </p>
                                    ) : null}
                                    {msg.meta.sources && msg.meta.sources.length > 0 ? (
                                      <div>
                                        <p className="mb-0.5">Sources</p>
                                        <ul className="list-disc pl-4 space-y-0.5">
                                          {msg.meta.sources.slice(0, 2).map((s, i) => (
                                            <li key={i}>{s.substring(0, 150)}…</li>
                                          ))}
                                        </ul>
                                      </div>
                                    ) : null}
                                  </div>
                                ) : null}
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
