export type CurrentUser = {
  id: number
  email: string
  full_name: string
  is_active: boolean
  created_at?: string | null
}

/** Keep TopBar email warm across soft navigations and short reloads. */
const TTL_MS = 300_000
const SS_KEY = "ga_current_user_v1"

type CacheEntry = { data: CurrentUser; at: number }

let cache: CacheEntry | null = null
let inflight: Promise<CurrentUser | null> | null = null

function readSession(): CacheEntry | null {
  if (typeof window === "undefined") return null
  try {
    const raw = sessionStorage.getItem(SS_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as CacheEntry
    if (!parsed?.data?.id || typeof parsed.at !== "number") return null
    if (Date.now() - parsed.at >= TTL_MS) return null
    return parsed
  } catch {
    return null
  }
}

function writeSession(entry: CacheEntry | null) {
  if (typeof window === "undefined") return
  try {
    if (!entry) sessionStorage.removeItem(SS_KEY)
    else sessionStorage.setItem(SS_KEY, JSON.stringify(entry))
  } catch {
    /* private mode / quota */
  }
}

export function clearCurrentUserCache() {
  cache = null
  inflight = null
  writeSession(null)
}

export function seedCurrentUserCache(data: CurrentUser) {
  cache = { data, at: Date.now() }
  inflight = null
  writeSession(cache)
  // Owner flip guest→user: drop previous owner-scoped dashboard caches
  try {
    void import("@/lib/historical-analytics-store").then((m) => m.clearOwnerScopedCaches())
  } catch {
    /* ignore */
  }
}

export function peekCurrentUserCache(): CurrentUser | null {
  if (cache && Date.now() - cache.at < TTL_MS) return cache.data
  const fromSs = readSession()
  if (fromSs) {
    cache = fromSs
    return fromSs.data
  }
  return null
}

type Fetcher = () => Promise<Response>

export async function fetchCurrentUserCached(
  apiFetch: Fetcher,
): Promise<CurrentUser | null> {
  const peek = peekCurrentUserCache()
  if (peek) return peek
  if (inflight) return inflight

  inflight = (async () => {
    try {
      const res = await apiFetch()
      if (!res.ok) {
        cache = null
        writeSession(null)
        return null
      }
      const data = (await res.json()) as CurrentUser
      cache = { data, at: Date.now() }
      writeSession(cache)
      return data
    } catch {
      cache = null
      writeSession(null)
      return null
    } finally {
      inflight = null
    }
  })()

  return inflight
}
