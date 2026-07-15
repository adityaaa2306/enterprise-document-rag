"use client"

import { useEffect, useState } from "react"
import { motion } from "framer-motion"
import { useRouter } from "next/navigation"
import { Sidebar } from "@/components/sidebar"
import { TopBar } from "@/components/top-bar"
import { Button } from "@/components/ui/button"
import { API_BASE_URL } from "@/config"
import { apiLogout } from "@/lib/api"
import { useCurrentUser } from "@/hooks/use-current-user"
import { clearGuestSessionLocal } from "@/lib/guest-session"
import { CheckCircle2, XCircle, Server, User, LogOut, Mail } from "lucide-react"
import Link from "next/link"

export default function SettingsPage() {
  const router = useRouter()
  const { user, guest, isGuest, loading: userLoading } = useCurrentUser()
  const [apiOk, setApiOk] = useState<boolean | null>(null)
  const [apiDetail, setApiDetail] = useState<string>("")
  const [loggingOut, setLoggingOut] = useState(false)

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

  const handleLogout = async () => {
    setLoggingOut(true)
    try {
      if (isGuest) {
        clearGuestSessionLocal()
        router.push("/")
        return
      }
      await apiLogout(true)
      router.push("/login")
    } finally {
      setLoggingOut(false)
    }
  }

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

            <section className="rounded-lg border border-border bg-card p-6 space-y-4 mb-6">
              <div className="flex items-start gap-3">
                <User className="w-5 h-5 text-primary mt-0.5" />
                <div className="min-w-0 flex-1">
                  <h2 className="font-medium mb-1">Account</h2>
                  <p className="text-sm text-muted-foreground">
                    {isGuest
                      ? "You are in Demo Mode. Sign in to persist history and manage an account."
                      : "Your signed-in email for this browser session."}
                  </p>
                </div>
              </div>

              <div className="pt-3 border-t border-border space-y-4">
                {isGuest ? (
                  <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 space-y-2">
                    <p className="text-sm font-medium text-amber-50">
                      Guest · {guest?.anonymous_name || "Demo session"}
                    </p>
                    <p className="text-xs text-amber-100/70">
                      Account settings require sign-in. Upgrading transfers this session’s work to your account.
                    </p>
                    <Button asChild className="mt-1">
                      <Link href="/login?next=/settings">Sign in to upgrade</Link>
                    </Button>
                  </div>
                ) : (
                  <div className="rounded-lg bg-muted/40 border border-border px-4 py-3 space-y-1">
                    <p className="text-xs text-muted-foreground">Email</p>
                    {userLoading ? (
                      <p className="text-sm text-muted-foreground">Loading account…</p>
                    ) : (
                      <div className="flex items-center gap-2">
                        <Mail className="w-4 h-4 text-muted-foreground shrink-0" />
                        <span className="break-all font-medium text-foreground">
                          {user?.email || "Not signed in"}
                        </span>
                      </div>
                    )}
                    {user?.full_name ? (
                      <p className="text-sm text-muted-foreground pl-6 pt-1">
                        {user.full_name}
                      </p>
                    ) : null}
                  </div>
                )}

                <Button
                  type="button"
                  variant="outline"
                  onClick={handleLogout}
                  disabled={loggingOut || userLoading}
                  className="w-full sm:w-auto border-border text-destructive hover:text-destructive hover:bg-destructive/10"
                >
                  <LogOut className="w-4 h-4" />
                  {loggingOut
                    ? isGuest
                      ? "Ending…"
                      : "Signing out…"
                    : isGuest
                      ? "End demo"
                      : "Log out"}
                </Button>
              </div>
            </section>

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
          </motion.div>
        </main>
      </div>
    </div>
  )
}
