"use client"

import { useEffect, useState, type ReactNode } from "react"
import { getAccessToken } from "@/lib/api"
import { ensureGuestSession, getGuestSessionId } from "@/lib/guest-session"

/**
 * Ensures every app shell has an Owner before children fire API calls.
 * JWT users: no-op. Anonymous visitors: create/resume guest session.
 * Never redirects to /login.
 *
 * Always start `ready=false` so SSR HTML matches the first client paint
 * (avoids GuestOwnerGate → Sidebar button hydration mismatches when
 * sessionStorage already has a guest id).
 */
export function GuestOwnerGate({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        if (getAccessToken()) {
          if (!cancelled) setReady(true)
          return
        }
        if (getGuestSessionId()) {
          if (!cancelled) setReady(true)
          void ensureGuestSession().catch(() => undefined)
          return
        }
        await ensureGuestSession()
        if (!cancelled) setReady(true)
      } catch (e) {
        console.error("[Guest] Owner gate failed", e)
        if (!cancelled) {
          setError(
            e instanceof Error
              ? e.message
              : "Could not start a guest demo session. Is the API running?",
          )
          setReady(true)
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background text-sm text-muted-foreground">
        Starting demo session…
      </div>
    )
  }

  return (
    <>
      {error ? (
        <div className="border-b border-amber-500/40 bg-amber-500/10 px-4 py-2 text-center text-xs text-amber-100">
          {error}{" "}
          <button
            type="button"
            className="underline"
            onClick={() => {
              setError(null)
              setReady(false)
              void ensureGuestSession()
                .then(() => setReady(true))
                .catch((err) => {
                  setError(err instanceof Error ? err.message : "Retry failed")
                  setReady(true)
                })
            }}
          >
            Retry
          </button>
        </div>
      ) : null}
      {children}
    </>
  )
}
