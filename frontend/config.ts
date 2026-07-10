// API Configuration
// Uses environment variable in production, falls back to localhost for development.
// Trailing slashes are stripped so paths like `${API_BASE_URL}/auth/login` stay valid.
export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
).replace(/\/$/, "")
