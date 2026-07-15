"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import {
  fetchGuestSessionInfo,
  getGuestMeta,
  getGuestSessionId,
  guestIdleRemainingLabel,
} from "@/lib/guest-session"
import { getAccessToken } from "@/lib/api"

export function GuestSessionBadge({ className = "" }: { className?: string }) {
  const [info, setInfo] = useState<{
    name?: string
    expires?: string
  } | null>(null)

  useEffect(() => {
    if (getAccessToken()) {
      setInfo(null)
      return
    }
    if (!getGuestSessionId()) return

    const apply = (name?: string, expires?: string) => {
      setInfo({ name, expires })
      if (expires && typeof window !== "undefined") {
        try {
          const raw = sessionStorage.getItem("ga_guest_meta")
          const meta = raw ? JSON.parse(raw) : {}
          sessionStorage.setItem(
            "ga_guest_meta",
            JSON.stringify({
              ...meta,
              expires_at: expires,
              anonymous_name: name || meta.anonymous_name,
            }),
          )
        } catch {
          /* ignore */
        }
      }
    }

    const meta = getGuestMeta()
    apply(meta?.anonymous_name, meta?.expires_at)

    const refresh = () => {
      void fetchGuestSessionInfo().then((data) => {
        if (!data || !data.is_guest) return
        apply(
          String(data.anonymous_name || meta?.anonymous_name || "Guest"),
          String(data.expires_at || meta?.expires_at || ""),
        )
      })
    }

    refresh()
    const t = setInterval(refresh, 30_000)
    return () => clearInterval(t)
  }, [])

  if (!info) return null

  return (
    <div
      className={`rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-100/90 ${className}`}
      data-testid="guest-session-badge"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded bg-amber-400/20 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-amber-200">
          Demo Mode
        </span>
        <span className="font-medium text-amber-50">
          Guest Session{info.name ? ` · ${info.name}` : ""}
        </span>
      </div>
      <div className="mt-1 text-amber-100/70 tabular-nums">
        Idle window · {guestIdleRemainingLabel(info.expires)} left · renews on activity
      </div>
      <div className="mt-0.5 text-amber-100/55">Temporary session — history not saved after expiry</div>
      <Link
        href="/login?next=/dashboard"
        className="mt-1.5 inline-block font-medium text-amber-200 underline-offset-2 hover:underline"
        data-testid="guest-upgrade-link"
      >
        Upgrade to save history →
      </Link>
    </div>
  )
}
