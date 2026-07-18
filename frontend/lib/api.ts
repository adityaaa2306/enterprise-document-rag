/**
 * Authenticated + Guest API client for the CarbonRoute AI backend.
 *
 * Auth modes:
 * - JWT: Authorization: Bearer <access_token>  (credentials omit)
 * - Guest: X-Guest-Session-Id from sessionStorage (credentials omit)
 *
 * Never use credentials: "include" for API calls — CORS_ORIGINS=* cannot
 * pair with Access-Control-Allow-Credentials, and guest identity is header-based.
 */
import { API_BASE_URL } from "@/config"
import { clearCurrentUserCache } from "@/lib/current-user-cache"
import { getGuestSessionId, isGuestMode } from "@/lib/guest-session"
import { clearOwnerScopedCaches } from "@/lib/historical-analytics-store"

const ACCESS_KEY = "access_token"
const REFRESH_KEY = "refresh_token"

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null
  return localStorage.getItem(ACCESS_KEY)
}

export function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null
  return localStorage.getItem(REFRESH_KEY)
}

export function setTokens(access: string, refresh?: string | null) {
  localStorage.setItem(ACCESS_KEY, access)
  if (refresh) {
    localStorage.setItem(REFRESH_KEY, refresh)
  }
}

export function clearTokens() {
  localStorage.removeItem(ACCESS_KEY)
  localStorage.removeItem(REFRESH_KEY)
  clearCurrentUserCache()
  clearOwnerScopedCaches()
}

let refreshPromise: Promise<boolean> | null = null

async function refreshAccessToken(): Promise<boolean> {
  const refresh = getRefreshToken()
  if (!refresh) return false
  try {
    const res = await fetch(`${API_BASE_URL}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "omit",
      body: JSON.stringify({ refresh_token: refresh }),
    })
    if (!res.ok) {
      clearTokens()
      return false
    }
    const data = await res.json()
    if (!data.access_token) {
      clearTokens()
      return false
    }
    setTokens(data.access_token, data.refresh_token || refresh)
    return true
  } catch {
    clearTokens()
    return false
  }
}

function redirectToLogin() {
  if (typeof window === "undefined") return
  // Guests must never bounce to /login for business routes
  if (isGuestMode()) return
  const path = window.location.pathname
  if (path === "/login" || path === "/signup" || path === "/") return
  const next = encodeURIComponent(path + (window.location.search || ""))
  window.location.replace(`/login?next=${next}`)
}

export type ApiFetchOptions = RequestInit & {
  /** Skip auth header (login/register) */
  skipAuth?: boolean
  /** Correlation id for logs (sent as X-Request-Id). Generated if omitted. */
  requestId?: string
}

export type ApiFetchMeta = {
  requestId: string
  startedAt: number
  finishedAt: number
  latencyMs: number
  status: number | null
  ok: boolean | null
  errorName: string | null
  errorMessage: string | null
  timedOut: boolean
  aborted: boolean
}

/**
 * fetch wrapper with Bearer auth + guest header + single refresh retry on 401.
 *
 * Optional ``metaOut`` is filled with timing / status / exception fields for
 * poll diagnostics (does not change response behavior).
 */
export async function apiFetch(
  path: string,
  options: ApiFetchOptions = {},
  metaOut?: Partial<ApiFetchMeta>,
): Promise<Response> {
  const { skipAuth, headers: initHeaders, requestId: reqIdOpt, ...rest } = options
  const headers = new Headers(initHeaders || {})
  const requestId =
    reqIdOpt ||
    (typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID().slice(0, 12)
      : `fe-${Date.now().toString(36)}`)
  headers.set("X-Request-Id", requestId)

  const token = skipAuth ? null : getAccessToken()
  let authMode: "jwt" | "guest" | "none" = "none"
  if (token) {
    headers.set("Authorization", `Bearer ${token}`)
    authMode = "jwt"
  } else if (!skipAuth) {
    const guestId = getGuestSessionId()
    if (guestId) {
      headers.set("X-Guest-Session-Id", guestId)
      authMode = "guest"
    }
  }

  if (typeof console !== "undefined" && process.env.NODE_ENV === "development") {
    console.debug(`[API] ${rest.method || "GET"} ${path} auth=${authMode} request_id=${requestId}`)
  }

  const url = path.startsWith("http") ? path : `${API_BASE_URL}${path.startsWith("/") ? "" : "/"}${path}`
  const startedAt = Date.now()
  if (metaOut) {
    metaOut.requestId = requestId
    metaOut.startedAt = startedAt
    metaOut.status = null
    metaOut.ok = null
    metaOut.errorName = null
    metaOut.errorMessage = null
    metaOut.timedOut = false
    metaOut.aborted = false
  }

  let res: Response
  try {
    res = await fetch(url, {
      ...rest,
      headers,
      // Always omit credentials — identity is Bearer or X-Guest-Session-Id
      credentials: "omit",
    })
  } catch (err) {
    const finishedAt = Date.now()
    const name = err instanceof Error ? err.name : typeof err
    const message = err instanceof Error ? err.message : String(err)
    if (metaOut) {
      metaOut.finishedAt = finishedAt
      metaOut.latencyMs = finishedAt - startedAt
      metaOut.errorName = name
      metaOut.errorMessage = message
      metaOut.aborted = name === "AbortError" || /aborted/i.test(message)
      metaOut.timedOut =
        name === "TimeoutError" || /timeout/i.test(message)
    }
    throw err
  }

  if (metaOut) {
    metaOut.finishedAt = Date.now()
    metaOut.latencyMs = metaOut.finishedAt - startedAt
    metaOut.status = res.status
    metaOut.ok = res.ok
  }

  if (res.status === 401 && !skipAuth && token) {
    if (!refreshPromise) {
      refreshPromise = refreshAccessToken().finally(() => {
        refreshPromise = null
      })
    }
    const ok = await refreshPromise
    if (!ok) {
      if (getGuestSessionId()) {
        const guestHeaders = new Headers(initHeaders || {})
        guestHeaders.set("X-Guest-Session-Id", getGuestSessionId()!)
        guestHeaders.set("X-Request-Id", requestId)
        res = await fetch(url, {
          ...rest,
          headers: guestHeaders,
          credentials: "omit",
        })
        if (metaOut) {
          metaOut.finishedAt = Date.now()
          metaOut.latencyMs = metaOut.finishedAt - startedAt
          metaOut.status = res.status
          metaOut.ok = res.ok
        }
        return res
      }
      redirectToLogin()
      return res
    }
    const retryHeaders = new Headers(initHeaders || {})
    retryHeaders.set("X-Request-Id", requestId)
    const newToken = getAccessToken()
    if (newToken) {
      retryHeaders.set("Authorization", `Bearer ${newToken}`)
    }
    res = await fetch(url, {
      ...rest,
      headers: retryHeaders,
      credentials: "omit",
    })
    if (metaOut) {
      metaOut.finishedAt = Date.now()
      metaOut.latencyMs = metaOut.finishedAt - startedAt
      metaOut.status = res.status
      metaOut.ok = res.ok
    }
    if (res.status === 401) {
      clearTokens()
      if (!getGuestSessionId()) redirectToLogin()
    }
  }

  return res
}

export async function apiLogout(revokeAll = false): Promise<void> {
  try {
    await apiFetch("/auth/logout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        refresh_token: getRefreshToken(),
        revoke_all: revokeAll,
      }),
    })
  } catch {
    // ignore
  } finally {
    clearTokens()
  }
}
