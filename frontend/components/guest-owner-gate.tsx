"use client"

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react"
import { getAccessToken } from "@/lib/api"
import {
  ensureGuestSession,
  fetchGuestSessionInfo,
  getGuestSessionId,
} from "@/lib/guest-session"

export type GuestOwnerState = {
  /** True when JWT or a guest session id is available for API calls. */
  ownerReady: boolean
  /** True while creating/resuming a guest session (no local id yet). */
  connecting: boolean
  error: string | null
  retry: () => void
}

const GuestOwnerContext = createContext<GuestOwnerState>({
  ownerReady: false,
  connecting: false,
  error: null,
  retry: () => undefined,
})

export function useGuestOwner(): GuestOwnerState {
  return useContext(GuestOwnerContext)
}

function warmAfterOwnerReady(isJwt: boolean): void {
  void Promise.allSettled([
    isJwt
      ? import("@/lib/current-user-cache").then(async (m) => {
          if (m.peekCurrentUserCache()) return
          const { apiFetch } = await import("@/lib/api")
          await m.fetchCurrentUserCached(() => apiFetch("/auth/me"))
        })
      : fetchGuestSessionInfo(),
    import("@/lib/finalized-metrics-store").then((m) =>
      m.ensureFinalizedMetrics({ force: false }).catch(() => null),
    ),
    import("@/lib/api").then(async ({ apiFetch }) => {
      await Promise.allSettled([
        apiFetch("/queue").then((r) => (r.ok ? r.json() : null)),
        apiFetch("/jobs?limit=1").then((r) => (r.ok ? r.json() : null)),
      ])
    }),
  ])
}

/**
 * Ensures every app shell has an Owner for API calls — without blocking paint.
 *
 * JWT users: ready immediately.
 * Existing guest id in sessionStorage: ready immediately (touch expiry in bg).
 * New anonymous visitors: render shell, create guest in background, then enable actions.
 *
 * Never full-screen gates. Never redirects to /login.
 */
export function GuestOwnerGate({ children }: { children: ReactNode }) {
  const [ownerReady, setOwnerReady] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [bootKey, setBootKey] = useState(0)

  const retry = useCallback(() => {
    setError(null)
    setBootKey((k) => k + 1)
  }, [])

  // Sync identity before paint (client navigations) so cached guests never flash "connecting"
  useLayoutEffect(() => {
    if (getAccessToken() || getGuestSessionId()) {
      setOwnerReady(true)
      setConnecting(false)
    } else {
      setOwnerReady(false)
      setConnecting(true)
    }
  }, [bootKey])

  useEffect(() => {
    let cancelled = false

    const run = async () => {
      try {
        if (getAccessToken()) {
          if (!cancelled) {
            setOwnerReady(true)
            setConnecting(false)
            setError(null)
          }
          warmAfterOwnerReady(true)
          return
        }

        const existing = getGuestSessionId()
        if (existing) {
          // Cached guest → already interactive; touch + warm in parallel
          if (!cancelled) {
            setOwnerReady(true)
            setConnecting(false)
            setError(null)
          }
          void ensureGuestSession()
            .then(() => {
              if (!cancelled) warmAfterOwnerReady(false)
            })
            .catch(() => undefined)
          return
        }

        if (!cancelled) {
          setOwnerReady(false)
          setConnecting(true)
          setError(null)
        }

        await ensureGuestSession()
        if (cancelled) return
        setOwnerReady(true)
        setConnecting(false)
        warmAfterOwnerReady(false)
      } catch (e) {
        console.error("[Guest] Owner bootstrap failed", e)
        if (!cancelled) {
          setError(
            e instanceof Error
              ? e.message
              : "Could not start a guest demo session. Is the API running?",
          )
          setConnecting(false)
          // Keep shell visible; upload stays disabled until retry succeeds
          setOwnerReady(Boolean(getGuestSessionId() || getAccessToken()))
        }
      }
    }

    void run()
    return () => {
      cancelled = true
    }
  }, [bootKey])

  const value = useMemo(
    () => ({ ownerReady, connecting, error, retry }),
    [ownerReady, connecting, error, retry],
  )

  return (
    <GuestOwnerContext.Provider value={value}>
      {error ? (
        <div className="border-b border-amber-500/40 bg-amber-500/10 px-4 py-2 text-center text-xs text-amber-100">
          {error}{" "}
          <button type="button" className="underline" onClick={retry}>
            Retry
          </button>
        </div>
      ) : null}
      {children}
    </GuestOwnerContext.Provider>
  )
}
