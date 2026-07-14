/**
 * Authenticated API client for the Green Agentic backend.
 * - Attaches Authorization: Bearer <access_token>
 * - On 401, attempts refresh via /auth/refresh then retries once
 * - Redirects to /login when refresh fails
 */
import { API_BASE_URL } from "@/config"
import { clearCurrentUserCache } from "@/lib/current-user-cache"

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
}

let refreshPromise: Promise<boolean> | null = null

async function refreshAccessToken(): Promise<boolean> {
  const refresh = getRefreshToken()
  if (!refresh) return false
  try {
    const res = await fetch(`${API_BASE_URL}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // Bearer/body auth only — omit credentials so CORS_ORIGINS=* works in prod
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
  const path = window.location.pathname
  if (path !== "/login" && path !== "/signup") {
    window.location.href = "/login"
  }
}

export type ApiFetchOptions = RequestInit & {
  /** Skip auth header (login/register) */
  skipAuth?: boolean
}

/**
 * fetch wrapper with Bearer auth + single refresh retry on 401.
 */
export async function apiFetch(path: string, options: ApiFetchOptions = {}): Promise<Response> {
  const { skipAuth, headers: initHeaders, ...rest } = options
  const headers = new Headers(initHeaders || {})

  if (!skipAuth) {
    const token = getAccessToken()
    if (token) {
      headers.set("Authorization", `Bearer ${token}`)
    }
  }

  const url = path.startsWith("http") ? path : `${API_BASE_URL}${path.startsWith("/") ? "" : "/"}${path}`

  let res = await fetch(url, {
    ...rest,
    headers,
    credentials: rest.credentials ?? "omit",
  })

  if (res.status === 401 && !skipAuth) {
    if (!refreshPromise) {
      refreshPromise = refreshAccessToken().finally(() => {
        refreshPromise = null
      })
    }
    const ok = await refreshPromise
    if (!ok) {
      redirectToLogin()
      return res
    }
    const retryHeaders = new Headers(initHeaders || {})
    const newToken = getAccessToken()
    if (newToken) {
      retryHeaders.set("Authorization", `Bearer ${newToken}`)
    }
    res = await fetch(url, {
      ...rest,
      headers: retryHeaders,
      credentials: rest.credentials ?? "omit",
    })
    if (res.status === 401) {
      clearTokens()
      redirectToLogin()
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
