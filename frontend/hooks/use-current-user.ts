"use client"

import { useEffect, useState } from "react"
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

function initialUser(): CurrentUser | null {
  if (typeof window === "undefined") return null
  if (!getAccessToken()) return null
  return peekCurrentUserCache()
}

function initialGuest(): GuestSessionInfo | null {
  if (typeof window === "undefined") return null
  if (getAccessToken()) return null
  if (!(isGuestMode() || getGuestSessionId())) return null
  const id = getGuestSessionId()
  if (!id) return null
  return getGuestMeta() || { guest_session_id: id }
}

/**
 * Resolves Authenticated vs Guest vs Anonymous.
 * Guests never call /auth/me (JWT-only endpoint → 401).
 * Hydrates from cache synchronously to avoid TopBar flash / blocking loads.
 */
export function useCurrentUser() {
  const [user, setUser] = useState<CurrentUser | null>(initialUser)
  const [guest, setGuest] = useState<GuestSessionInfo | null>(initialGuest)
  const [loading, setLoading] = useState(() => {
    if (typeof window === "undefined") return true
    if (peekCurrentUserCache() && getAccessToken()) return false
    if (getGuestSessionId() && !getAccessToken()) return false
    return Boolean(getAccessToken())
  })
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const token = getAccessToken()
        if (token) {
          const cached = peekCurrentUserCache()
          if (cached) {
            setUser(cached)
            setGuest(null)
            setLoading(false)
          }
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
