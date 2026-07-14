"use client"

import { useMemo, useState } from "react"
import { ChevronDown } from "lucide-react"
import { cn } from "@/lib/utils"

export type LatencyPayload = {
  stages_ms?: Record<string, number>
  meta?: Record<string, unknown>
}

export type FrontendTiming = {
  /** Client wall clock from fetch start to stream done (ms) */
  client_wall_ms: number
  /** Time until first response byte / first SSE token if measured; else null */
  ttfb_ms?: number | null
  /** Time until first content token rendered (ms) — perceived TTFT */
  perceived_ttft_ms?: number | null
  /** Generation throughput from backend meta when available */
  tokens_per_sec?: number | null
}

const STAGE_LABELS: Record<string, string> = {
  query_embed_ms: "Query embedding",
  dense_retrieve_ms: "Dense / Chroma search",
  bm25_retrieve_ms: "BM25 search",
  rrf_fuse_ms: "RRF fusion",
  rerank_ms: "Reranker",
  parent_expand_ms: "Parent expansion",
  retrieval_total_ms: "Retrieval total",
  context_assemble_ms: "Context assembly",
  nim_request_ms: "NIM request (total)",
  nim_network_ms: "NIM first byte / network",
  llm_ttft_ms: "Time to first token",
  llm_ttlt_ms: "Time to last token",
  llm_generation_ms: "LLM generation",
  explainability_ms: "Explainability",
  citations_ms: "Citation serialization",
  postprocess_ms: "Response post-process",
  total_ms: "Backend total",
}

const WATERFALL_SKIP = new Set(["retrieval_total_ms", "llm_generation_ms", "total_ms"])

function fmtMs(ms: number | null | undefined) {
  if (ms == null || !Number.isFinite(ms)) return "—"
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`
  return `${ms.toFixed(1)} ms`
}

function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {}
}

type Props = {
  latency: LatencyPayload | null | undefined
  frontend: FrontendTiming | null | undefined
  defaultOpen?: boolean
}

/**
 * Developer-only performance waterfall — uses only measured stages_ms / meta.
 */
export function QueryPerformancePanel({ latency, frontend, defaultOpen = true }: Props) {
  const [open, setOpen] = useState(defaultOpen)

  const stages = latency?.stages_ms || {}
  const meta = asRecord(latency?.meta)
  const nim = asRecord(meta.nim)
  const prompt = asRecord(meta.prompt)
  const embedding = asRecord(meta.embedding)
  const pipeline = asRecord(meta.pipeline_validation)
  const resourcesEnd = asRecord(meta.resources_end)

  const backendTotal = Number(stages.total_ms)
  const clientWall = frontend?.client_wall_ms ?? null
  const networkApprox =
    clientWall != null && Number.isFinite(backendTotal)
      ? Math.max(0, clientWall - backendTotal)
      : null

  const rows = useMemo(() => {
    const entries = Object.entries(stages)
      .filter(([k]) => k !== "total_ms")
      .map(([key, ms]) => ({ key, ms: Number(ms) || 0 }))
      .sort((a, b) => b.ms - a.ms)

    const denom = backendTotal > 0 ? backendTotal : entries.reduce((s, e) => s + e.ms, 0) || 1
    return entries.map((e) => ({
      ...e,
      label: STAGE_LABELS[e.key] || e.key,
      pct: (100 * e.ms) / denom,
    }))
  }, [stages, backendTotal])

  const waterfall = useMemo(() => {
    const order = [
      "query_embed_ms",
      "dense_retrieve_ms",
      "bm25_retrieve_ms",
      "rrf_fuse_ms",
      "rerank_ms",
      "parent_expand_ms",
      "context_assemble_ms",
      "nim_network_ms",
      "llm_ttft_ms",
      "llm_ttlt_ms",
      "postprocess_ms",
      "explainability_ms",
      "citations_ms",
    ]
    const items = order
      .filter((k) => k in stages && !WATERFALL_SKIP.has(k))
      .map((k) => ({ key: k, ms: Number(stages[k]) || 0, label: STAGE_LABELS[k] || k }))
    const peak = Math.max(...items.map((i) => i.ms), 1)
    return { items, peak }
  }, [stages])

  if (!latency?.stages_ms || Object.keys(stages).length === 0) {
    return (
      <div className="rounded-lg border border-border/40 bg-muted/15 px-3 py-2 text-xs text-muted-foreground">
        Performance: waiting for measured latency from /rag-query.
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-amber-500/25 bg-amber-500/5 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-3 py-2 text-left"
      >
        <span className="text-[11px] font-semibold uppercase tracking-wide text-amber-200/90">
          Performance (developer)
        </span>
        <ChevronDown
          className={cn(
            "h-3.5 w-3.5 text-muted-foreground transition-transform",
            open && "rotate-180",
          )}
        />
      </button>

      {open ? (
        <div className="space-y-4 border-t border-border/40 px-3 py-3">
          <div className="grid grid-cols-2 gap-2">
            <Stat label="TTFT" value={fmtMs(Number(stages.llm_ttft_ms))} emphasize />
            <Stat
              label="Tokens/sec"
              value={
                (() => {
                  const fromNim = Number(nim.tokens_per_sec)
                  const fromPrompt = Number(prompt.tokens_per_sec)
                  const fromFe = frontend?.tokens_per_sec
                  const v =
                    (Number.isFinite(fromNim) && fromNim > 0 && fromNim) ||
                    (Number.isFinite(fromPrompt) && fromPrompt > 0 && fromPrompt) ||
                    (fromFe != null && fromFe > 0 ? fromFe : null)
                  return v != null ? `${Number(v).toFixed(1)}` : "—"
                })()
              }
              emphasize
            />
            <Stat label="Backend total" value={fmtMs(backendTotal)} />
            <Stat label="Frontend wall" value={fmtMs(clientWall)} />
            <Stat
              label="Perceived TTFT"
              value={fmtMs(frontend?.perceived_ttft_ms ?? frontend?.ttfb_ms)}
            />
            <Stat label="TTLT" value={fmtMs(Number(stages.llm_ttlt_ms))} />
            <Stat label="Network (FE−BE)" value={fmtMs(networkApprox)} />
            <Stat
              label="Pipeline clean"
              value={pipeline.clean === false ? "VIOLATION" : "Yes"}
            />
          </div>

          <div>
            <p className="mb-1.5 text-[10px] uppercase tracking-wide text-muted-foreground">
              Waterfall (measured)
            </p>
            <ul className="space-y-1">
              {waterfall.items.map((item) => (
                <li key={item.key} className="flex items-center gap-2 text-[11px]">
                  <span className="w-[7.5rem] shrink-0 truncate text-muted-foreground" title={item.label}>
                    {item.label}
                  </span>
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted/40">
                    <div
                      className="h-full rounded-full bg-emerald-400/80"
                      style={{ width: `${Math.max(2, (item.ms / waterfall.peak) * 100)}%` }}
                    />
                  </div>
                  <span className="w-14 shrink-0 text-right tabular-nums">{fmtMs(item.ms)}</span>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <p className="mb-1.5 text-[10px] uppercase tracking-wide text-muted-foreground">
              Stages (% of backend total)
            </p>
            <div className="max-h-48 overflow-auto rounded border border-border/30">
              <table className="w-full text-[11px]">
                <thead className="sticky top-0 bg-card text-muted-foreground">
                  <tr>
                    <th className="px-2 py-1 text-left font-medium">Stage</th>
                    <th className="px-2 py-1 text-right font-medium">ms</th>
                    <th className="px-2 py-1 text-right font-medium">%</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.key} className="border-t border-border/20">
                      <td className="px-2 py-1">{r.label}</td>
                      <td className="px-2 py-1 text-right tabular-nums">{r.ms.toFixed(1)}</td>
                      <td className="px-2 py-1 text-right tabular-nums">{r.pct.toFixed(1)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {Object.keys(prompt).length > 0 ? (
            <MetaBlock
              title="Prompt tokens"
              entries={[
                ["System", prompt.system_tokens],
                ["Query", prompt.user_query_tokens],
                ["Context", prompt.retrieved_context_tokens],
                ["Final prompt", prompt.final_prompt_tokens],
                ["Output", prompt.output_tokens],
                ["Max tokens", prompt.max_tokens_cap],
                ["Tok/s", prompt.tokens_per_sec],
                [
                  "Plan",
                  prompt.response_plan && typeof prompt.response_plan === "object"
                    ? `${(prompt.response_plan as { query_type?: string }).query_type || "?"} / ${(prompt.response_plan as { max_tokens?: number }).max_tokens ?? "?"}`
                    : null,
                ],
              ]}
            />
          ) : null}

          {Object.keys(nim).length > 0 ? (
            <MetaBlock
              title="NIM"
              entries={[
                ["Model", nim.model_used],
                ["Primary", nim.primary_model],
                ["Fallback used", String(nim.fallback_used)],
                ["Retries", nim.retry_count],
                ["HTTP", nim.http_status],
                ["First byte", fmtMs(Number(nim.first_byte_ms))],
                ["Inference", fmtMs(Number(nim.inference_ms))],
                ["Tokens/sec", nim.tokens_per_sec],
              ]}
            />
          ) : null}

          {Object.keys(embedding).length > 0 ? (
            <MetaBlock
              title="Embedding"
              entries={[
                ["Model", embedding.embedding_model],
                ["Cache hits", embedding.cache_hits],
                ["Cache misses", embedding.cache_misses],
                ["API ms", embedding.embed_api_ms],
                ["Dim", embedding.dim],
              ]}
            />
          ) : null}

          <MetaBlock
            title="Retrieval meta"
            entries={[
              ["Mode", meta.retrieval_mode],
              ["Retrieved", meta.retrieved_chunks],
              ["Reranked", meta.reranked_chunks],
              ["Top-K", meta.top_k],
            ]}
          />

          <MetaBlock
            title="Resources (end)"
            entries={[
              ["RSS MB", resourcesEnd.rss_mb],
              ["CPU %", resourcesEnd.cpu_percent],
              ["Threads", resourcesEnd.num_threads ?? meta.active_threads],
              ["GPU %", resourcesEnd.gpu_util_percent],
              ["GPU mem MB", resourcesEnd.gpu_mem_used_mb],
            ]}
          />
        </div>
      ) : null}
    </div>
  )
}

function Stat({
  label,
  value,
  emphasize,
}: {
  label: string
  value: string
  emphasize?: boolean
}) {
  return (
    <div
      className={cn(
        "rounded-md border px-2 py-1.5",
        emphasize
          ? "border-emerald-500/35 bg-emerald-500/10"
          : "border-border/40 bg-muted/20",
      )}
    >
      <p className="text-[10px] text-muted-foreground">{label}</p>
      <p className="text-xs font-semibold tabular-nums">{value}</p>
    </div>
  )
}

function MetaBlock({
  title,
  entries,
}: {
  title: string
  entries: Array<[string, unknown]>
}) {
  const visible = entries.filter(([, v]) => v != null && v !== "")
  if (!visible.length) return null
  return (
    <div>
      <p className="mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">{title}</p>
      <dl className="grid grid-cols-2 gap-x-2 gap-y-1 text-[11px]">
        {visible.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-2 border-b border-border/15 py-0.5">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="truncate font-medium tabular-nums" title={String(v)}>
              {String(v)}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  )
}
