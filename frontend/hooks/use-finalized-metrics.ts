"use client"

import { useCallback, useEffect, useState } from "react"
import {
  ensureFinalizedMetrics,
  peekFinalizedMetrics,
  snapshotSyncKey,
  subscribeFinalizedMetrics,
  type FinalizedMetricsSnapshot,
} from "@/lib/finalized-metrics-store"

/**
 * Subscribe to the shared finalized-job store (Layer 1).
 * Re-renders when job_id / revision / updated_at / ownerKey change — not on object identity.
 */
export function useFinalizedMetrics(options?: { refreshOnMount?: boolean }) {
  const refreshOnMount = options?.refreshOnMount !== false
  const [snap, setSnap] = useState<FinalizedMetricsSnapshot | null>(() =>
    peekFinalizedMetrics(),
  )
  const [syncKey, setSyncKey] = useState(() => snapshotSyncKey(peekFinalizedMetrics()))
  const [loading, setLoading] = useState(() => !peekFinalizedMetrics())

  useEffect(() => {
    const unsub = subscribeFinalizedMetrics((next) => {
      const key = snapshotSyncKey(next)
      setSyncKey((prev) => {
        if (prev === key) return prev
        return key
      })
      setSnap(next)
      if (next) setLoading(false)
    })
    if (refreshOnMount) {
      void ensureFinalizedMetrics()
        .then((next) => {
          setSnap(next)
          setSyncKey(snapshotSyncKey(next))
        })
        .finally(() => setLoading(false))
    } else {
      setLoading(false)
    }
    return unsub
  }, [refreshOnMount])

  const refresh = useCallback(async (force = false) => {
    if (force) setLoading(true)
    try {
      const next = await ensureFinalizedMetrics({ force })
      setSnap(next)
      setSyncKey(snapshotSyncKey(next))
      return next
    } finally {
      setLoading(false)
    }
  }, [])

  return {
    snapshot: snap,
    syncKey,
    jobId: snap?.jobId ?? null,
    revision: snap?.revision ?? 0,
    updatedAt: snap?.updatedAt ?? "",
    result: snap?.result ?? null,
    metrics: snap?.metrics ?? null,
    loading: loading && !snap,
    refresh,
  }
}
