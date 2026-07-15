"use client"

import { useMemo } from "react"

type NodeStatus =
  | "pending"
  | "ready"
  | "running"
  | "completed"
  | "failed"
  | "retrying"
  | "waiting"
  | "skipped"

type KindBucket = {
  done?: number
  total?: number
  running?: number
  failed?: number
  pending?: number
  retrying?: number
}

type DagSnapshot = {
  by_kind?: Record<string, KindBucket>
  chunks?: KindBucket
  regional?: KindBucket
  chapter?: KindBucket
  executive?: KindBucket
  workers_busy?: number
  workers_total?: number
  avg_latency_ms?: number
  carbon_g?: number
  remaining?: number
  eta_sec?: number | null
  completed?: number
  total?: number
}

const LEVELS: { key: string; label: string; optional?: boolean }[] = [
  { key: "chunk", label: "Chunks" },
  { key: "regional", label: "Regional", optional: true },
  { key: "chapter", label: "Chapter", optional: true },
  { key: "executive", label: "Executive" },
]

function statusForBucket(
  b?: KindBucket,
  opts?: { dagKnown?: boolean; optional?: boolean },
): NodeStatus {
  const total = b?.total ?? 0
  // Optional levels (regional/chapter) with total=0 mean the planner omitted them.
  if (opts?.dagKnown && opts?.optional && total === 0) return "skipped"
  if (!b || !total) return "waiting"
  if ((b.running || 0) > 0) return "running"
  if ((b.retrying || 0) > 0) return "retrying"
  if ((b.failed || 0) > 0 && (b.done || 0) < total) return "failed"
  if ((b.done || 0) >= total && total > 0) return "completed"
  if ((b.pending || 0) > 0 || (b.done || 0) < total) return "waiting"
  return "pending"
}

function tone(status: NodeStatus): string {
  switch (status) {
    case "running":
      return "border-emerald-400/60 bg-emerald-500/10 text-emerald-300"
    case "completed":
      return "border-emerald-600/40 bg-emerald-950/40 text-emerald-200"
    case "failed":
      return "border-red-500/50 bg-red-950/30 text-red-300"
    case "retrying":
      return "border-amber-400/50 bg-amber-950/30 text-amber-200"
    case "skipped":
      return "border-white/10 bg-white/[0.02] text-neutral-500"
    default:
      return "border-white/10 bg-white/[0.03] text-neutral-400"
  }
}

function statusLabel(status: NodeStatus): string {
  if (status === "skipped") return "Skipped (not required by planner)"
  return status
}

function LevelCard({
  label,
  bucket,
  dagKnown,
  optional,
}: {
  label: string
  bucket?: KindBucket
  dagKnown?: boolean
  optional?: boolean
}) {
  const status = statusForBucket(bucket, { dagKnown, optional })
  const done = bucket?.done ?? 0
  const total = bucket?.total ?? 0
  const pct = total > 0 ? Math.round((done / total) * 100) : 0
  return (
    <div className={`rounded-lg border px-4 py-3 min-w-[140px] ${tone(status)}`}>
      <div className="font-mono text-[10px] uppercase tracking-[0.18em] opacity-70">{label}</div>
      <div className="mt-1 text-lg font-medium tabular-nums">
        {status === "skipped" ? "0" : total > 0 ? `${done}/${total}` : "—"}
      </div>
      <div className="mt-1 flex items-center justify-between gap-2">
        <span className="font-mono text-[10px] uppercase tracking-wider leading-snug">
          {statusLabel(status)}
        </span>
        {total > 0 ? (
          <span className="font-mono text-[10px] tabular-nums opacity-70">{pct}%</span>
        ) : null}
      </div>
      {total > 0 ? (
        <div className="mt-2 h-1 w-full rounded-full bg-black/30 overflow-hidden">
          <div
            className="h-full bg-current opacity-70 transition-all duration-300"
            style={{ width: `${Math.min(100, pct)}%` }}
          />
        </div>
      ) : null}
    </div>
  )
}

export function ExecutionGraph({
  dag,
  workersBusy,
  workersTotal,
  avgLatencyMs,
  carbonG,
  remaining,
  etaSec,
  progress,
}: {
  dag?: DagSnapshot | null
  workersBusy?: number | null
  workersTotal?: number | null
  avgLatencyMs?: number | null
  carbonG?: number | null
  remaining?: number | null
  etaSec?: number | null
  progress?: number
}) {
  const buckets = useMemo(() => {
    const by = dag?.by_kind || {}
    return {
      chunk: dag?.chunks || by.chunk,
      regional: dag?.regional || by.regional,
      chapter: dag?.chapter || by.chapter,
      executive: dag?.executive || by.executive || by.final,
    }
  }, [dag])

  // Topology known once any level reports a total (planner produced a DAG snapshot).
  const dagKnown = Boolean(
    dag &&
      ((buckets.chunk?.total ?? 0) > 0 ||
        (buckets.executive?.total ?? 0) > 0 ||
        (dag.total ?? 0) > 0 ||
        Object.keys(dag.by_kind || {}).length > 0),
  )

  const busy = workersBusy ?? dag?.workers_busy ?? 0
  const totalW = workersTotal ?? dag?.workers_total ?? 0
  const lat = avgLatencyMs ?? dag?.avg_latency_ms
  const carbon = carbonG ?? dag?.carbon_g
  const rem = remaining ?? dag?.remaining
  const eta = etaSec ?? dag?.eta_sec

  return (
    <div className="space-y-4 rounded-xl border border-border/50 bg-card/40 p-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
            Live execution graph
          </div>
          <div className="text-sm text-foreground/90 mt-1">
            Document → Chunks → Regional → Chapter → Executive → Final
          </div>
        </div>
        <div className="font-mono text-[11px] tabular-nums text-muted-foreground">
          {typeof progress === "number" ? `${Math.round(progress)}%` : null}
          {eta != null ? ` · ETA ${Math.max(0, Math.round(eta))}s` : null}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 md:gap-3">
        <div className="rounded-lg border border-white/10 bg-white/[0.03] px-4 py-3 text-neutral-300">
          <div className="font-mono text-[10px] uppercase tracking-[0.18em] opacity-70">Document</div>
          <div className="mt-1 text-sm">root</div>
        </div>
        <span className="text-muted-foreground hidden sm:inline">→</span>
        {LEVELS.map((lv, i) => (
          <div key={lv.key} className="flex items-center gap-2 md:gap-3">
            {i > 0 ? <span className="text-muted-foreground hidden sm:inline">→</span> : null}
            <LevelCard
              label={lv.label}
              bucket={buckets[lv.key as keyof typeof buckets]}
              dagKnown={dagKnown}
              optional={lv.optional}
            />
          </div>
        ))}
        <span className="text-muted-foreground hidden sm:inline">→</span>
        <LevelCard
          label="Final"
          dagKnown={dagKnown}
          bucket={
            buckets.executive?.total
              ? {
                  done: (buckets.executive.done || 0) >= (buckets.executive.total || 0) ? 1 : 0,
                  total: 1,
                  running: buckets.executive.running,
                }
              : undefined
          }
        />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 font-mono text-[11px] text-muted-foreground">
        <div>
          Workers{" "}
          <span className="text-foreground tabular-nums">
            {busy}/{totalW || "—"}
          </span>
        </div>
        <div>
          Avg latency{" "}
          <span className="text-foreground tabular-nums">
            {lat != null ? `${Math.round(lat)}ms` : "—"}
          </span>
        </div>
        <div>
          Carbon{" "}
          <span className="text-foreground tabular-nums">
            {carbon != null ? `${Number(carbon).toFixed(3)}g` : "—"}
          </span>
        </div>
        <div>
          Remaining{" "}
          <span className="text-foreground tabular-nums">{rem != null ? rem : "—"}</span>
        </div>
      </div>
    </div>
  )
}
