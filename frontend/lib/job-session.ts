/**
 * Persist the active job ID across navigation / refreshes (per browser).
 * Only the latest job is kept — older job ids are discarded locally.
 *
 * Guest Mode: also key by guest session id so the same demo owner keeps the
 * job for the full 2h idle window across reloads.
 */
import { getGuestSessionId } from "@/lib/guest-session"

const LAST_JOB_KEY = "gar_last_job_id"
const RECENT_JOBS_KEY = "gar_recent_job_ids"

function guestJobKey(guestId: string) {
  return `gar_guest_job:${guestId}`
}

export function rememberJobId(jobId: string) {
  if (typeof window === "undefined" || !jobId) return
  localStorage.setItem(LAST_JOB_KEY, jobId)
  localStorage.setItem(RECENT_JOBS_KEY, JSON.stringify([jobId]))
  const guestId = getGuestSessionId()
  if (guestId) {
    try {
      sessionStorage.setItem(guestJobKey(guestId), jobId)
      localStorage.setItem(guestJobKey(guestId), jobId)
    } catch {
      /* ignore */
    }
  }
  try {
    const prefix = "green-rag-chat:"
    const keepSuffix = `:${jobId}`
    const toRemove: string[] = []
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i)
      if (key && key.startsWith(prefix) && !key.endsWith(keepSuffix)) {
        toRemove.push(key)
      }
    }
    toRemove.forEach((k) => localStorage.removeItem(k))
  } catch {
    // ignore
  }
}

export function getLastJobId(): string | null {
  if (typeof window === "undefined") return null
  const guestId = getGuestSessionId()
  if (guestId) {
    try {
      const fromGuest =
        sessionStorage.getItem(guestJobKey(guestId)) ||
        localStorage.getItem(guestJobKey(guestId))
      if (fromGuest) return fromGuest
    } catch {
      /* ignore */
    }
    // Guests must not inherit the global last-job key (often another Owner → 403).
    return null
  }
  return localStorage.getItem(LAST_JOB_KEY)
}

export function getRecentJobIds(): string[] {
  if (typeof window === "undefined") return []
  try {
    const last = getLastJobId()
    if (last) return [last]
    const raw = localStorage.getItem(RECENT_JOBS_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    const ids = parsed.filter((x) => typeof x === "string")
    return ids.slice(0, 1)
  } catch {
    return []
  }
}

export function clearLastJobId() {
  if (typeof window === "undefined") return
  localStorage.removeItem(LAST_JOB_KEY)
  localStorage.removeItem(RECENT_JOBS_KEY)
  const guestId = getGuestSessionId()
  if (guestId) {
    try {
      sessionStorage.removeItem(guestJobKey(guestId))
      localStorage.removeItem(guestJobKey(guestId))
    } catch {
      /* ignore */
    }
  }
}
