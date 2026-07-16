/**
 * Client-side input guards (defense in depth; server remains authoritative).
 */

export const MAX_QUERY_CHARS = 8000
export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024
export const GUEST_MAX_UPLOAD_BYTES = 25 * 1024 * 1024

const ALLOWED_UPLOAD_EXT = new Set([".pdf", ".docx", ".txt", ".csv"])
const SCRIPT_RE =
  /<\s*script\b|javascript\s*:|on\w+\s*=|<\s*iframe\b|<\s*object\b|<\s*embed\b/i
const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

export function stripControls(value: string, allowNewlines = true): string {
  const noNul = (value || "").replace(/\0/g, "")
  if (allowNewlines) {
    return noNul.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, "").trim()
  }
  return noNul.replace(/[\u0000-\u001F\u007F]/g, "").trim()
}

export function sanitizeQuery(raw: string): string {
  const text = stripControls(raw, true)
  if (!text) throw new Error("Query must not be empty")
  if (text.length > MAX_QUERY_CHARS) {
    throw new Error(`Query must be at most ${MAX_QUERY_CHARS} characters`)
  }
  if (SCRIPT_RE.test(text)) {
    throw new Error("Query contains disallowed script content")
  }
  return text
}

export function isUuid(value: string | null | undefined): boolean {
  if (!value) return false
  return UUID_RE.test(stripControls(value, false))
}

export function validateUploadFile(
  file: File,
  opts?: { maxBytes?: number },
): { ok: true } | { ok: false; error: string } {
  const maxBytes = opts?.maxBytes ?? MAX_UPLOAD_BYTES
  if (!file || !(file instanceof File)) {
    return { ok: false, error: "No file selected" }
  }
  if (file.size <= 0) {
    return { ok: false, error: "Empty file" }
  }
  if (file.size > maxBytes) {
    return {
      ok: false,
      error: `File too large. Limit is ${Math.floor(maxBytes / (1024 * 1024))} MB.`,
    }
  }
  const name = (file.name || "").split(/[/\\]/).pop() || ""
  const dot = name.lastIndexOf(".")
  const ext = dot >= 0 ? name.slice(dot).toLowerCase() : ""
  if (!ALLOWED_UPLOAD_EXT.has(ext)) {
    return {
      ok: false,
      error: `Unsupported file type. Allowed: ${[...ALLOWED_UPLOAD_EXT].join(", ")}`,
    }
  }
  if (SCRIPT_RE.test(name)) {
    return { ok: false, error: "Invalid file name" }
  }
  return { ok: true }
}

/** Open-redirect safe path from ?next= */
export function safeNextPath(raw: string | null | undefined): string {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//")) return "/dashboard"
  if (raw.includes("://")) return "/dashboard"
  if (/[\0\r\n]/.test(raw)) return "/dashboard"
  return raw
}
