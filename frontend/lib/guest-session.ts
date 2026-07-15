/**
 * Guest session client helpers.
 *
 * Architecture: guest identity is the session UUID in sessionStorage, sent as
 * ``X-Guest-Session-Id`` on every API call. Cookies are optional/same-origin
 * only — never required. Requests use credentials: "omit" so CORS_ORIGINS=*
 * (and localhost ↔ 127.0.0.1) works without Access-Control-Allow-Credentials.
 */
import { API_BASE_URL } from "@/config"

const GUEST_KEY = "ga_guest_session_id"
const GUEST_META_KEY = "ga_guest_meta"

export type GuestSessionInfo = {
  guest_session_id: string
  anonymous_name?: string
  expires_at?: string
  status?: string
  resumed?: boolean
}

function logGuest(event: string, detail?: Record<string, unknown>) {
  if (typeof console !== "undefined") {
    console.info(`[Guest] ${event}`, detail || "")
  }
}

export function getGuestSessionId(): string | null {
  if (typeof window === "undefined") return null
  return sessionStorage.getItem(GUEST_KEY)
}

export function isGuestMode(): boolean {
  if (typeof window === "undefined") return false
  try {
    if (localStorage.getItem("access_token")) return false
  } catch {
    /* ignore */
  }
  return Boolean(getGuestSessionId())
}

export function clearGuestSessionLocal(): void {
  if (typeof window === "undefined") return
  sessionStorage.removeItem(GUEST_KEY)
  sessionStorage.removeItem(GUEST_META_KEY)
  try {
    // Dynamic to avoid circular import with api/stores during module init
    void import("@/lib/historical-analytics-store").then((m) => m.clearOwnerScopedCaches())
  } catch {
    /* ignore */
  }
  logGuest("Guest Session Cleared")
}

export function getGuestMeta(): GuestSessionInfo | null {
  if (typeof window === "undefined") return null
  try {
    const raw = sessionStorage.getItem(GUEST_META_KEY)
    return raw ? (JSON.parse(raw) as GuestSessionInfo) : null
  } catch {
    return null
  }
}

function persistGuest(data: GuestSessionInfo): void {
  if (!data.guest_session_id) return
  sessionStorage.setItem(GUEST_KEY, data.guest_session_id)
  sessionStorage.setItem(GUEST_META_KEY, JSON.stringify(data))
}

export async function ensureGuestSession(): Promise<GuestSessionInfo> {
  const existing = getGuestSessionId()
  const headers: Record<string, string> = { "Content-Type": "application/json" }
  if (existing) headers["X-Guest-Session-Id"] = existing

  logGuest(existing ? "Guest Session Resume Attempt" : "Guest Session Create Attempt")

  const res = await fetch(`${API_BASE_URL}/guest/session`, {
    method: "POST",
    headers,
    // Header-based identity — never credentials:include (breaks CORS *)
    credentials: "omit",
  })
  if (!res.ok) {
    const text = await res.text().catch(() => "")
    logGuest("Guest Session Failed", { status: res.status, text: text.slice(0, 200) })
    throw new Error(`Guest session failed (${res.status})`)
  }
  const data = (await res.json()) as GuestSessionInfo
  persistGuest(data)
  logGuest(data.resumed ? "Guest Session Loaded" : "Guest Session Created", {
    guest_session_id: data.guest_session_id,
    anonymous_name: data.anonymous_name,
    expires_at: data.expires_at,
  })
  return data
}

export async function fetchGuestSessionInfo(): Promise<Record<string, unknown> | null> {
  const id = getGuestSessionId()
  if (!id) return null
  const { apiFetch } = await import("@/lib/api")
  const res = await apiFetch("/guest/session")
  if (!res.ok) {
    if (res.status === 401) logGuest("Guest Session Expired")
    return null
  }
  const data = (await res.json()) as Record<string, unknown>
  if (data.is_guest && data.guest_session_id) {
    persistGuest({
      guest_session_id: String(data.guest_session_id),
      anonymous_name: data.anonymous_name ? String(data.anonymous_name) : undefined,
      expires_at: data.expires_at ? String(data.expires_at) : undefined,
      status: data.status ? String(data.status) : undefined,
    })
    logGuest("Guest Session Loaded", {
      guest_session_id: data.guest_session_id,
      expires_at: data.expires_at,
    })
  }
  return data
}

export async function upgradeGuestAfterLogin(): Promise<boolean> {
  const id = getGuestSessionId()
  if (!id) return false
  const { apiFetch } = await import("@/lib/api")
  logGuest("Guest Upgrade Attempt", { guest_session_id: id })
  const res = await apiFetch("/guest/upgrade", {
    method: "POST",
    headers: { "X-Guest-Session-Id": id },
  })
  if (res.ok) {
    clearGuestSessionLocal()
    logGuest("Guest Upgrade Succeeded")
    return true
  }
  logGuest("Guest Upgrade Failed", { status: res.status })
  return false
}

/** Time left until the 2h inactivity window closes (sliding; resets on API use). */
export function guestIdleRemainingLabel(expiresAt?: string | null): string {
  if (!expiresAt) return "—"
  const end = new Date(expiresAt).getTime()
  const ms = end - Date.now()
  if (ms <= 0) return "ended"
  const totalMin = Math.floor(ms / 60000)
  const h = Math.floor(totalMin / 60)
  const m = totalMin % 60
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`
}

/** @deprecated use guestIdleRemainingLabel */
export const guestExpiresInLabel = guestIdleRemainingLabel
