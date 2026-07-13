"use client"

import { useEffect, useState } from "react"
import { apiFetch } from "@/lib/api"

export interface CurrentUser {
  id: number
  email: string
  full_name: string
  is_active: boolean
  created_at?: string | null
}

export function useCurrentUser() {
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const res = await apiFetch("/auth/me")
        if (!res.ok) {
          if (!cancelled) {
            setUser(null)
            setError(`HTTP ${res.status}`)
          }
          return
        }
        const data = (await res.json()) as CurrentUser
        if (!cancelled) {
          setUser(data)
          setError(null)
        }
      } catch (e) {
        if (!cancelled) {
          setUser(null)
          setError(e instanceof Error ? e.message : "Failed to load user")
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  return { user, loading, error }
}
