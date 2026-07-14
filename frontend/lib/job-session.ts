/**
 * Persist active job IDs across navigation / refreshes (per browser).
 * Server-side /jobs is the source of truth between sessions; this keeps
 * the Results tab sticky when switching sidebar sections.
 */
const LAST_JOB_KEY = "gar_last_job_id"
const RECENT_JOBS_KEY = "gar_recent_job_ids"

export function rememberJobId(jobId: string) {
  if (typeof window === "undefined" || !jobId) return
  localStorage.setItem(LAST_JOB_KEY, jobId)
  const prev = getRecentJobIds().filter((id) => id !== jobId)
  const next = [jobId, ...prev].slice(0, 20)
  localStorage.setItem(RECENT_JOBS_KEY, JSON.stringify(next))
}

export function getLastJobId(): string | null {
  if (typeof window === "undefined") return null
  return localStorage.getItem(LAST_JOB_KEY)
}

export function getRecentJobIds(): string[] {
  if (typeof window === "undefined") return []
  try {
    const raw = localStorage.getItem(RECENT_JOBS_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter((x) => typeof x === "string") : []
  } catch {
    return []
  }
}

export function clearLastJobId() {
  if (typeof window === "undefined") return
  localStorage.removeItem(LAST_JOB_KEY)
}
