export type CurrentUser = {
  id: number
  email: string
  full_name: string
  is_active: boolean
  created_at?: string | null
}

const TTL_MS = 30_000

type CacheEntry = { data: CurrentUser; at: number }

let cache: CacheEntry | null = null
let inflight: Promise<CurrentUser | null> | null = null

export function clearCurrentUserCache() {
  cache = null
  inflight = null
}

export function seedCurrentUserCache(data: CurrentUser) {
  cache = { data, at: Date.now() }
  inflight = null
}

export function peekCurrentUserCache(): CurrentUser | null {
  if (cache && Date.now() - cache.at < TTL_MS) return cache.data
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
        return null
      }
      const data = (await res.json()) as CurrentUser
      cache = { data, at: Date.now() }
      return data
    } catch {
      cache = null
      return null
    } finally {
      inflight = null
    }
  })()

  return inflight
}
