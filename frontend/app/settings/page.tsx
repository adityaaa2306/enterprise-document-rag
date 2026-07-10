"use client"

import { useEffect, useState } from "react"
import { motion } from "framer-motion"
import { Sidebar } from "@/components/sidebar"
import { TopBar } from "@/components/top-bar"
import { API_BASE_URL } from "@/config"
import { CheckCircle2, XCircle, Server } from "lucide-react"

export default function SettingsPage() {
  const [apiOk, setApiOk] = useState<boolean | null>(null)
  const [apiDetail, setApiDetail] = useState<string>("")

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/health`)
        const body = await res.json().catch(() => ({}))
        if (cancelled) return
        setApiOk(res.ok)
        setApiDetail(
          res.ok
            ? `${body.service || "API"} · ${body.env || "unknown"} · ${body.version || ""}`
            : `HTTP ${res.status}`,
        )
      } catch (e) {
        if (cancelled) return
        setApiOk(false)
        setApiDetail(e instanceof Error ? e.message : "Unreachable")
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="flex">
      <Sidebar />
      <div className="flex-1">
        <TopBar />
        <main className="p-8 max-w-2xl">
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <h1 className="text-3xl font-bold mb-2">Settings</h1>
            <p className="text-muted-foreground mb-8">
              Connection and account details for this portfolio deployment.
            </p>

            <section className="rounded-lg border border-border bg-card p-6 space-y-4">
              <div className="flex items-start gap-3">
                <Server className="w-5 h-5 text-primary mt-0.5" />
                <div className="min-w-0 flex-1">
                  <h2 className="font-medium mb-1">Backend API</h2>
                  <p className="text-sm text-muted-foreground break-all font-mono">
                    {API_BASE_URL}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2 text-sm pt-2 border-t border-border">
                {apiOk === null && (
                  <span className="text-muted-foreground">Checking health…</span>
                )}
                {apiOk === true && (
                  <>
                    <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                    <span>Reachable — {apiDetail}</span>
                  </>
                )}
                {apiOk === false && (
                  <>
                    <XCircle className="w-4 h-4 text-destructive" />
                    <span>Unreachable — {apiDetail}</span>
                  </>
                )}
              </div>
            </section>

            <p className="text-xs text-muted-foreground mt-6">
              Auth uses Bearer tokens stored in this browser. Use Log out in the
              sidebar to clear the session.
            </p>
          </motion.div>
        </main>
      </div>
    </div>
  )
}
