"use client"

import { useEffect, useLayoutEffect, useState } from "react"
import { apiFetch, getAccessToken } from "@/lib/api"
import {
  fetchCurrentUserCached,
  peekCurrentUserCache,
  clearCurrentUserCache,
  type CurrentUser,
} from "@/lib/current-user-cache"
import {
  getGuestMeta,
  getGuestSessionId,
  isGuestMode,
  type GuestSessionInfo,
} from "@/lib/guest-session"

export type { CurrentUser }
export { clearCurrentUserCache }

export type AuthPersona =
  | { kind: "user"; user: CurrentUser }
  | { kind: "guest"; guest: GuestSessionInfo }
  | { kind: "anonymous" }

/**
 * Resolves Authenticated vs Guest vs Anonymous.
 * Guests never call /auth/me (JWT-only endpoint → 401).
 *
 * Initial state is always SSR-safe (null / loading). Reading localStorage during
 * useState init caused hydration mismatches (server: Platform Dashboard,
 * client: Guest Session). Cache is applied in useEffect after mount.
 */
export function useCurrentUser() {
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [guest, setGuest] = useState<GuestSessionInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // After hydration, apply localStorage cache before paint to limit chrome flash.
  useLayoutEffect(() => {
    const token = getAccessToken()
    if (token) {
      const cached = peekCurrentUserCache()
      if (cached) {
        setUser(cached)
        setGuest(null)
        setLoading(false)
      }
      return
    }
    if (isGuestMode() || getGuestSessionId()) {
      const id = getGuestSessionId()
      if (!id) return
      setUser(null)
      setGuest(getGuestMeta() || { guest_session_id: id })
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const token = getAccessToken()
        if (token) {
          const data = await fetchCurrentUserCached(() => apiFetch("/auth/me"))
          if (cancelled) return
          if (!data) {
            setUser(null)
            setError("Unauthenticated")
            const meta = getGuestMeta()
            const id = getGuestSessionId()
            if (id) {
              setGuest(meta || { guest_session_id: id })
              setError(null)
            }
          } else {
            setUser(data)
            setGuest(null)
            setError(null)
          }
          return
        }

        if (isGuestMode() || getGuestSessionId()) {
          const meta = getGuestMeta()
          const id = getGuestSessionId()!
          setUser(null)
          setGuest(meta || { guest_session_id: id })
          setError(null)
          return
        }

        setUser(null)
        setGuest(null)
        setError(null)
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

  const isGuest = Boolean(guest && !user)
  const isAuthenticated = Boolean(user)

  return {
    user,
    guest,
    isGuest,
    isAuthenticated,
    loading,
    error,
  }
}
