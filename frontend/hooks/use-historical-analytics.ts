"use client"

import { useCallback, useEffect, useState } from "react"
import {
  ensureHistoricalAnalytics,
  peekHistoricalAnalytics,
  subscribeHistoricalAnalytics,
  type HistoricalAnalytics,
  type RangeKey,
} from "@/lib/historical-analytics-store"

export function useHistoricalAnalytics(options: {
  range: RangeKey
  customStart?: string
  customEnd?: string
  refreshOnMount?: boolean
}) {
  const refreshOnMount = options.refreshOnMount !== false
  const [stats, setStats] = useState<HistoricalAnalytics | null>(() =>
    peekHistoricalAnalytics(),
  )
  const [loading, setLoading] = useState(() => !peekHistoricalAnalytics())

  useEffect(() => {
    const unsub = subscribeHistoricalAnalytics((next) => {
      setStats(next)
      if (next) setLoading(false)
    })
    if (refreshOnMount) {
      void ensureHistoricalAnalytics({
        range: options.range,
        customStart: options.customStart,
        customEnd: options.customEnd,
      })
        .then(setStats)
        .finally(() => setLoading(false))
    } else {
      setLoading(false)
    }
    return unsub
  }, [refreshOnMount, options.range, options.customStart, options.customEnd])

  const refresh = useCallback(
    async (force = false) => {
      setLoading(true)
      try {
        const next = await ensureHistoricalAnalytics({
          range: options.range,
          customStart: options.customStart,
          customEnd: options.customEnd,
          force,
        })
        setStats(next)
        return next
      } finally {
        setLoading(false)
      }
    },
    [options.range, options.customStart, options.customEnd],
  )

  return {
    stats,
    loading: loading && !stats,
    refresh,
  }
}
