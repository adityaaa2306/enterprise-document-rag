"use client"

import dynamic from "next/dynamic"
import { useEffect, useMemo, useState, useTransition } from "react"
import { motion } from "framer-motion"
import {
  Clock3,
  DollarSign,
  Gauge,
  Leaf,
  Zap,
} from "lucide-react"
import { Sidebar } from "@/components/sidebar"
import { TopBar } from "@/components/top-bar"
import { GuestOwnerGate } from "@/components/guest-owner-gate"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { BenchmarkModelTable } from "@/components/benchmark/benchmark-model-table"
import { BenchmarkQuestionExplorer } from "@/components/benchmark/benchmark-question-explorer"
import { BenchmarkSummaryExplorer } from "@/components/benchmark/benchmark-summary-explorer"
import { BenchmarkMethodology } from "@/components/benchmark/benchmark-methodology"
import { BenchmarkAnalyticsSkeleton } from "@/components/benchmark/benchmark-analytics-skeleton"
import { BenchmarkInsights } from "@/components/benchmark/benchmark-insights"
import { BenchmarkKpiPanel } from "@/components/benchmark/benchmark-kpi-panel"
import { BenchmarkTradeoff } from "@/components/benchmark/benchmark-tradeoff"
import { BenchmarkWorkloadCostCo2 } from "@/components/benchmark/benchmark-workload-cost-co2"
import {
  campaignWorkload,
  filterCampaignsByWorkload,
  fmtDate,
  fmtNum,
  fmtUsd,
  listBenchmarkCampaigns,
  loadCampaignBundle,
  pickCrossWorkloadPair,
  pickDefaultCampaign,
} from "@/lib/benchmark-campaigns"
import type {
  BenchmarkWorkload,
  CampaignBundle,
  CampaignIndexEntry,
} from "@/lib/benchmark-types"
import { cn } from "@/lib/utils"

const BenchmarkCharts = dynamic(
  () => import("@/components/benchmark/benchmark-charts"),
  {
    ssr: false,
    loading: () => <BenchmarkAnalyticsSkeleton />,
  },
)

function MetaChip({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border/50 bg-black/25 px-3 py-2.5 min-w-0">
      <p className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground mb-1">
        {label}
      </p>
      <p className="text-sm font-medium text-foreground truncate" title={value}>
        {value}
      </p>
    </div>
  )
}

function CampaignSelect({
  label,
  value,
  onChange,
  campaigns,
}: {
  label: string
  value: string
  onChange: (id: string) => void
  campaigns: CampaignIndexEntry[]
}) {
  return (
    <div className="w-full min-w-0">
      <label className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground mb-1.5 block">
        {label}
      </label>
      <Select value={value} onValueChange={onChange} disabled={!campaigns.length}>
        <SelectTrigger className="bg-card/60 border-border/60">
          <SelectValue placeholder="Select a campaign" />
        </SelectTrigger>
        <SelectContent>
          {campaigns.map((c) => (
            <SelectItem key={c.campaign_id} value={c.campaign_id}>
              <span className="flex items-center gap-2">
                <span>{c.label || c.campaign_id}</span>
                {c.status === "failed" ? (
                  <span className="text-[10px] text-red-300">failed</span>
                ) : null}
              </span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

export default function BenchmarkAnalyticsPage() {
  const [workload, setWorkload] = useState<BenchmarkWorkload>("interactive_rag")
  const [campaigns, setCampaigns] = useState<CampaignIndexEntry[]>([])
  const [selectedId, setSelectedId] = useState<string>("")
  const [bundle, setBundle] = useState<CampaignBundle | null>(null)
  const [ragPairBundle, setRagPairBundle] = useState<CampaignBundle | null>(null)
  const [sumPairBundle, setSumPairBundle] = useState<CampaignBundle | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loadingList, setLoadingList] = useState(true)
  const [loadingBundle, setLoadingBundle] = useState(false)
  const [pending, startTransition] = useTransition()

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        setLoadingList(true)
        const rows = await listBenchmarkCampaigns()
        if (cancelled) return
        setCampaigns(rows)
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      } finally {
        if (!cancelled) setLoadingList(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const filteredCampaigns = useMemo(
    () => filterCampaignsByWorkload(campaigns, workload),
    [campaigns, workload],
  )

  useEffect(() => {
    const preferred = pickDefaultCampaign(filteredCampaigns, workload)
    setSelectedId(preferred?.campaign_id || "")
    setBundle(null)
  }, [workload, filteredCampaigns])

  useEffect(() => {
    if (!selectedId) return
    let cancelled = false
    const hint = filteredCampaigns.find((c) => c.campaign_id === selectedId)
    startTransition(() => {
      setLoadingBundle(true)
      setError(null)
    })
    ;(async () => {
      try {
        const data = await loadCampaignBundle(selectedId, hint)
        if (cancelled) return
        startTransition(() => {
          setBundle(data)
          setLoadingBundle(false)
        })
      } catch (e) {
        if (cancelled) return
        startTransition(() => {
          setError(e instanceof Error ? e.message : String(e))
          setLoadingBundle(false)
        })
      }
    })()
    return () => {
      cancelled = true
    }
  }, [selectedId, filteredCampaigns])

  useEffect(() => {
    if (!campaigns.length) return
    const pair = pickCrossWorkloadPair(campaigns)
    const ragId = pair.rag?.campaign_id
    const sumId = pair.summarization?.campaign_id
    if (!ragId && !sumId) {
      setRagPairBundle(null)
      setSumPairBundle(null)
      return
    }
    let cancelled = false
    ;(async () => {
      try {
        const [ragData, sumData] = await Promise.all([
          ragId
            ? loadCampaignBundle(
                ragId,
                campaigns.find((c) => c.campaign_id === ragId),
              ).catch(() => null)
            : Promise.resolve(null),
          sumId
            ? loadCampaignBundle(
                sumId,
                campaigns.find((c) => c.campaign_id === sumId),
              ).catch(() => null)
            : Promise.resolve(null),
        ])
        if (cancelled) return
        startTransition(() => {
          setRagPairBundle(ragData)
          setSumPairBundle(sumData)
        })
      } catch {
        if (!cancelled) {
          startTransition(() => {
            setRagPairBundle(null)
            setSumPairBundle(null)
          })
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [campaigns])

  const selectedIndex = useMemo(
    () => filteredCampaigns.find((c) => c.campaign_id === selectedId) || null,
    [filteredCampaigns, selectedId],
  )
  const isSummarization = workload === "document_summarization"

  const dash = bundle?.dashboard
  const totals = dash?.totals
  const showSkeleton = loadingList || (loadingBundle && !bundle) || pending

  const totalRuns = useMemo(() => {
    if (!dash) return null
    const fromTable = (dash.table?.per_model || []).reduce(
      (acc, r) => acc + (r.n_runs || 0),
      0,
    )
    if (fromTable > 0) return fromTable
    const q = totals?.questions ?? bundle?.config.question_count ?? 0
    return q * (dash.models?.length || 0)
  }, [dash, totals, bundle])

  return (
    <GuestOwnerGate>
      <div className="flex min-h-screen bg-background">
        <Sidebar />
        <div className="flex-1 flex flex-col min-w-0">
          <TopBar />
          <main className="flex-1 overflow-y-auto">
            <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-8 space-y-10">
              <motion.section
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4 }}
                className="space-y-5"
              >
                <div className="flex flex-col xl:flex-row xl:items-end xl:justify-between gap-5">
                  <div className="min-w-0">
                    <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-emerald-400/90 mb-2">
                      Offline evaluation
                    </p>
                    <h1 className="text-3xl font-semibold tracking-tight text-foreground">
                      Benchmark Analytics
                    </h1>
                    <p className="text-sm text-muted-foreground mt-2 max-w-2xl leading-relaxed">
                      Decision support from immutable campaign artifacts. Switch
                      workloads to inspect Interactive RAG or Document Summarization —
                      without running any benchmarks.
                    </p>
                  </div>

                  <div className="inline-flex rounded-xl border border-emerald-500/35 bg-black/40 p-1.5 shadow-[0_0_0_1px_rgba(16,185,129,0.08)] shrink-0">
                    <button
                      type="button"
                      onClick={() => setWorkload("interactive_rag")}
                      className={cn(
                        "rounded-lg px-5 py-2.5 text-sm font-semibold tracking-tight transition-all",
                        workload === "interactive_rag"
                          ? "bg-emerald-500/20 text-emerald-100 shadow-sm ring-1 ring-emerald-400/40"
                          : "text-neutral-400 hover:text-foreground hover:bg-white/5",
                      )}
                    >
                      Interactive RAG
                    </button>
                    <button
                      type="button"
                      onClick={() => setWorkload("document_summarization")}
                      className={cn(
                        "rounded-lg px-5 py-2.5 text-sm font-semibold tracking-tight transition-all",
                        workload === "document_summarization"
                          ? "bg-emerald-500/20 text-emerald-100 shadow-sm ring-1 ring-emerald-400/40"
                          : "text-neutral-400 hover:text-foreground hover:bg-white/5",
                      )}
                    >
                      Document Summarization
                    </button>
                  </div>
                </div>

                <div className="w-full lg:w-[360px]">
                  <CampaignSelect
                    label="Campaign"
                    value={selectedId}
                    onChange={setSelectedId}
                    campaigns={filteredCampaigns}
                  />
                </div>

                {bundle || selectedIndex ? (
                  <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-8 gap-2.5">
                    <MetaChip
                      label="Workload"
                      value={
                        isSummarization
                          ? "Document Summarization"
                          : "Interactive RAG"
                      }
                    />
                    <MetaChip
                      label="Benchmark version"
                      value={
                        bundle?.metadata.benchmark_version ||
                        selectedIndex?.benchmark_version ||
                        "—"
                      }
                    />
                    <MetaChip
                      label="Campaign"
                      value={selectedIndex?.label || selectedId || "—"}
                    />
                    <MetaChip
                      label="Document"
                      value={
                        selectedIndex?.document_name ||
                        bundle?.config.filename ||
                        "Student Attendance App.pdf"
                      }
                    />
                    <MetaChip
                      label="Generated"
                      value={fmtDate(
                        bundle?.metadata.timestamp_utc || selectedIndex?.timestamp_utc,
                      )}
                    />
                    <MetaChip
                      label="Total runs"
                      value={totalRuns != null ? String(totalRuns) : "—"}
                    />
                    <MetaChip
                      label="Prompt tokens"
                      value={
                        totals?.total_prompt_tokens != null
                          ? Math.round(totals.total_prompt_tokens).toLocaleString()
                          : "—"
                      }
                    />
                    <MetaChip
                      label="Completion tokens"
                      value={
                        totals?.total_completion_tokens != null
                          ? Math.round(totals.total_completion_tokens).toLocaleString()
                          : "—"
                      }
                    />
                    <MetaChip
                      label="Campaign duration"
                      value={
                        totals?.total_runtime_sec != null ||
                        selectedIndex?.total_runtime_sec != null
                          ? `${fmtNum(
                              totals?.total_runtime_sec ??
                                selectedIndex?.total_runtime_sec,
                              1,
                            )} s`
                          : "—"
                      }
                    />
                  </div>
                ) : null}
              </motion.section>

              {error ? (
                <Card className="p-4 border-red-500/30 bg-red-500/5 text-sm text-red-200">
                  {error}
                </Card>
              ) : null}

              {ragPairBundle || sumPairBundle ? (
                <section>
                  <BenchmarkWorkloadCostCo2
                    rag={ragPairBundle}
                    summarization={sumPairBundle}
                  />
                </section>
              ) : null}

              {showSkeleton && !bundle ? (
                <BenchmarkAnalyticsSkeleton />
              ) : bundle && dash ? (
                <>
                  <section className="space-y-4">
                    <h2 className="text-sm font-medium uppercase tracking-[0.14em] text-muted-foreground">
                      Executive summary
                    </h2>
                    <BenchmarkKpiPanel bundle={bundle} />
                  </section>

                  <section>
                    <BenchmarkInsights bundle={bundle} />
                  </section>

                  <section>
                    <BenchmarkTradeoff dashboard={dash} />
                  </section>

                  <section>
                    <BenchmarkCharts dashboard={dash} />
                  </section>

                  <section>
                    <BenchmarkModelTable rows={dash.table?.per_model || []} />
                  </section>

                  <section>
                    {isSummarization ||
                    campaignWorkload(bundle) === "document_summarization" ? (
                      <BenchmarkSummaryExplorer questions={bundle.questions} />
                    ) : (
                      <BenchmarkQuestionExplorer questions={bundle.questions} />
                    )}
                  </section>

                  <section>
                    <BenchmarkMethodology workload={workload} />
                  </section>

                  <section className="space-y-4 pb-8">
                    <div>
                      <h2 className="text-sm font-medium uppercase tracking-[0.14em] text-muted-foreground">
                        Campaign history
                      </h2>
                      <p className="text-xs text-muted-foreground mt-1">
                        Showing {isSummarization ? "summarization" : "Interactive RAG"}{" "}
                        campaigns only. Failed campaigns stay available but are never
                        selected by default.
                      </p>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      {filteredCampaigns.map((c) => {
                        const active = c.campaign_id === selectedId
                        return (
                          <button
                            key={c.campaign_id}
                            type="button"
                            onClick={() => setSelectedId(c.campaign_id)}
                            className={cn(
                              "text-left rounded-xl border p-4 transition-all duration-200",
                              "bg-gradient-to-br from-card to-card/40 hover:border-emerald-500/30",
                              active
                                ? "border-emerald-500/40 ring-1 ring-emerald-500/20"
                                : "border-border/50",
                            )}
                          >
                            <div className="flex items-start justify-between gap-3 mb-2">
                              <div className="min-w-0">
                                <p className="text-sm font-semibold truncate">
                                  {c.label || c.campaign_id}
                                </p>
                                <p className="text-[11px] text-muted-foreground font-mono mt-0.5 truncate">
                                  {c.campaign_id}
                                </p>
                              </div>
                              <Badge
                                variant="outline"
                                className={cn(
                                  "shrink-0 text-[10px]",
                                  c.status === "failed"
                                    ? "border-red-500/30 text-red-300"
                                    : "border-emerald-500/30 text-emerald-300",
                                )}
                              >
                                {c.status === "failed" ? "failed" : "ok"}
                              </Badge>
                            </div>
                            <div className="grid grid-cols-2 gap-2 text-[11px] text-muted-foreground">
                              <span className="inline-flex items-center gap-1.5">
                                <Clock3 className="w-3 h-3" />
                                {fmtDate(c.timestamp_utc)}
                              </span>
                              <span className="inline-flex items-center gap-1.5">
                                <Gauge className="w-3 h-3" />v{c.benchmark_version} ·{" "}
                                {c.suite}
                              </span>
                              <span className="inline-flex items-center gap-1.5">
                                <DollarSign className="w-3 h-3" />
                                {fmtUsd(c.total_api_cost_usd, 4)}
                              </span>
                              <span className="inline-flex items-center gap-1.5">
                                <Zap className="w-3 h-3" />
                                {fmtNum(c.total_runtime_sec, 1)} s
                              </span>
                              <span className="inline-flex items-center gap-1.5 col-span-2">
                                <Leaf className="w-3 h-3" />
                                {c.document_name || c.document_id}
                              </span>
                            </div>
                          </button>
                        )
                      })}
                    </div>
                  </section>
                </>
              ) : (
                <Card className="p-8 border-border/50 bg-card/40 text-sm text-muted-foreground">
                  No{" "}
                  {isSummarization
                    ? "Document Summarization"
                    : "Interactive RAG"}{" "}
                  campaigns found under{" "}
                  <code className="text-foreground">/benchmark-campaigns</code>. Run{" "}
                  <code className="text-foreground">
                    {isSummarization
                      ? "python run_benchmark.py --suite summarization-smoke"
                      : "python run_benchmark.py --suite smoke"}
                  </code>{" "}
                  to generate artifacts, then sync them into{" "}
                  <code className="text-foreground">
                    frontend/public/benchmark-campaigns
                  </code>
                  .
                </Card>
              )}
            </div>
          </main>
        </div>
      </div>
    </GuestOwnerGate>
  )
}
