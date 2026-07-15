// API Configuration
// Production (Vercel): set NEXT_PUBLIC_API_URL to the Render API origin (no trailing slash).
// Development: always prefer local API; ignore placeholder remote URLs left over from build tests.
const raw = (process.env.NEXT_PUBLIC_API_URL || "").trim()
const isDev = process.env.NODE_ENV !== "production"
const isPlaceholderRemote =
  /example-api\.onrender\.com|your-api\.onrender\.com/i.test(raw)

if (!raw && !isDev) {
  // Fail the production client bundle if the public API URL was never configured.
  // Without this, the browser silently calls localhost and appears "broken".
  throw new Error(
    "NEXT_PUBLIC_API_URL must be set for production builds (e.g. https://your-api.onrender.com)",
  )
}

const resolved =
  isDev && (!raw || isPlaceholderRemote)
    ? "http://127.0.0.1:8000"
    : raw || "http://localhost:8000"

export const API_BASE_URL = resolved.replace(/\/$/, "")
