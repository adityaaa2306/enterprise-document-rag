"use client"

import { useCallback, useEffect, useState } from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { apiFetch } from "@/lib/api"
import { rememberJobId } from "@/lib/job-session"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Loader2, XCircle, RefreshCw, ListTodo } from "lucide-react"

export type JobListItem = {
  job_id: string
  status: string
  progress: number
  message: string
  filename?: string | null
  claimed_by?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export type QueueSnapshot = {
  alive_workers: number
  worker_busy: boolean
  queued_count: number
  processing_count: number
  workers: Array<{
    worker_id?: string
    status?: string
    busy?: boolean
    current_job_id?: string | null
  }>
  active_jobs: JobListItem[]
}

type Props = {
  currentJobId?: string | null
  onSelectJob?: (jobId: string) => void
  pollMs?: number
}

function statusTone(status: string) {
  const s = (status || "").toLowerCase()
  if (s === "complete" || s === "completed") return "text-emerald-400"
  if (s === "error" || s === "failed") return "text-red-400"
  if (s === "cancelled" || s === "canceled") return "text-amber-400"
  if (s === "processing") return "text-sky-400"
  return "text-muted-foreground"
}

export function JobQueuePanel({ currentJobId, onSelectJob, pollMs = 2500 }: Props) {
  const router = useRouter()
  const [queue, setQueue] = useState<QueueSnapshot | null>(null)
  const [history, setHistory] = useState<JobListItem[]>([])
  const [cancelling, setCancelling] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const [qRes, hRes] = await Promise.all([
        apiFetch("/queue"),
        apiFetch("/jobs?limit=1"),
      ])
      if (qRes.ok) {
        setQueue(await qRes.json())
      }
      if (hRes.ok) {
        const data = await hRes.json()
        setHistory(Array.isArray(data.jobs) ? data.jobs : [])
      }
      setError(null)
    } catch {
      setError("Could not load job queue")
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    let inFlight = false
    const tick = async () => {
      if (cancelled || inFlight) return
      inFlight = true
      try {
        await refresh()
      } finally {
        inFlight = false
      }
    }
    tick()
    const id = setInterval(tick, pollMs)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [refresh, pollMs])

  const openJob = (jobId: string) => {
    rememberJobId(jobId)
    if (onSelectJob) onSelectJob(jobId)
    else router.push(`/results?job_id=${jobId}`)
  }

  const cancelJob = async (jobId: string) => {
    setCancelling(jobId)
    try {
      const res = await apiFetch(`/jobs/${jobId}/cancel`, { method: "POST" })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body?.detail || `Cancel failed (${res.status})`)
      }
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : "Cancel failed")
    } finally {
      setCancelling(null)
    }
  }

  const busyJob =
    queue?.active_jobs?.find((j) => j.status === "processing") ||
    queue?.active_jobs?.[0]

  return (
    <div className="space-y-4">
      <Card className="p-4 bg-card/50 border-border/50 space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold flex items-center gap-2">
              <ListTodo className="w-4 h-4" />
              Worker & queue
            </h3>
            <p className="text-xs text-muted-foreground mt-1">
              {queue == null
                ? "Loading worker status…"
                : queue.alive_workers === 0
                  ? "No live worker detected"
                  : queue.worker_busy
                    ? `Worker busy · ${queue.processing_count} processing · ${queue.queued_count} queued`
                    : `Worker idle · ${queue.queued_count} queued`}
            </p>
          </div>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="gap-1 bg-transparent"
            onClick={() => refresh()}
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Refresh
          </Button>
        </div>

        {queue?.worker_busy && (
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm space-y-2">
            <p className="font-medium text-amber-200">
              A job is occupying the worker
            </p>
            {busyJob ? (
              <>
                <p className="text-xs text-muted-foreground break-all">
                  {(busyJob.filename || "Document") +
                    ` · ${busyJob.status} · ${Math.round(busyJob.progress || 0)}%`}
                  <br />
                  {busyJob.message}
                </p>
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="bg-transparent"
                    onClick={() => openJob(busyJob.job_id)}
                  >
                    Open
                  </Button>
                  {(busyJob.status === "processing" || busyJob.status === "pending") && (
                    <Button
                      type="button"
                      size="sm"
                      variant="destructive"
                      className="gap-1"
                      disabled={cancelling === busyJob.job_id}
                      onClick={() => cancelJob(busyJob.job_id)}
                    >
                      {cancelling === busyJob.job_id ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <XCircle className="w-3.5 h-3.5" />
                      )}
                      Cancel & free worker
                    </Button>
                  )}
                </div>
              </>
            ) : (
              <p className="text-xs text-muted-foreground">
                The worker is busy (possibly another session&apos;s job). Check Your job
                below, or wait until it finishes.
              </p>
            )}
          </div>
        )}

        {error && <p className="text-xs text-red-400">{error}</p>}
      </Card>

      <Card className="p-4 bg-card/50 border-border/50 space-y-3">
        <h3 className="text-sm font-semibold">Your job</h3>
        <p className="text-xs text-muted-foreground">
          Only the latest job is kept. Starting a new job replaces the previous one.
        </p>
        <div className="space-y-2 max-h-80 overflow-y-auto">
          {history.length === 0 ? (
            <p className="text-sm text-muted-foreground">No jobs yet.</p>
          ) : (
            history.map((job) => {
              const active = job.job_id === currentJobId
              const canCancel =
                job.status === "pending" || job.status === "processing"
              return (
                <div
                  key={job.job_id}
                  className={`rounded-lg border px-3 py-2 text-sm ${
                    active ? "border-primary/50 bg-primary/10" : "border-border/40"
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <button
                      type="button"
                      className="text-left flex-1 min-w-0"
                      onClick={() => openJob(job.job_id)}
                    >
                      <div className="font-medium truncate">
                        {job.filename || job.job_id.slice(0, 8)}
                      </div>
                      <div className={`text-xs ${statusTone(job.status)}`}>
                        {job.status} · {Math.round(job.progress || 0)}%
                      </div>
                      <div className="text-xs text-muted-foreground truncate">
                        {job.message || job.job_id}
                      </div>
                    </button>
                    <div className="flex flex-col gap-1 shrink-0">
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="bg-transparent h-7 text-xs"
                        onClick={() => openJob(job.job_id)}
                      >
                        Open
                      </Button>
                      {canCancel && (
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          className="h-7 text-xs text-red-400"
                          disabled={cancelling === job.job_id}
                          onClick={() => cancelJob(job.job_id)}
                        >
                          Cancel
                        </Button>
                      )}
                    </div>
                  </div>
                </div>
              )
            })
          )}
        </div>
        <Link href="/new-job" className="text-xs text-primary hover:underline">
          Start a new job →
        </Link>
      </Card>
    </div>
  )
}
