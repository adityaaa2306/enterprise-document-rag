"use client"

import { useEffect, useState } from "react"
import { apiFetch } from "@/lib/api"
import {
  fetchCurrentUserCached,
  peekCurrentUserCache,
  clearCurrentUserCache,
  type CurrentUser,
} from "@/lib/current-user-cache"

export type { CurrentUser }
export { clearCurrentUserCache }

export function useCurrentUser() {
  const [user, setUser] = useState<CurrentUser | null>(() => peekCurrentUserCache())
  const [loading, setLoading] = useState(() => !peekCurrentUserCache())
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const data = await fetchCurrentUserCached(() => apiFetch("/auth/me"))
        if (cancelled) return
        if (!data) {
          setUser(null)
          setError("Unauthenticated")
        } else {
          setUser(data)
          setError(null)
        }
      } catch (e) {
        if (!cancelled) {
          setUser(null)
          setError(e instanceof Error ? e.message : "Failed to load user")
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  return { user, loading, error }
}
