"use client"

import { motion } from "framer-motion"
import { useRouter } from "next/navigation"
import { Bell, LogOut, Mail, Settings, User } from "lucide-react"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { apiLogout } from "@/lib/api"
import { useCurrentUser } from "@/hooks/use-current-user"
import { GuestSessionBadge } from "@/components/guest-session-badge"
import { clearGuestSessionLocal } from "@/lib/guest-session"

/**
 * Compact sticky chrome. Guest demo notice sits *below* the sticky bar so it
 * scrolls away with page content (mentioned once, not pinned forever).
 */
export function TopBar() {
  const router = useRouter()
  const { user, guest, isGuest, loading } = useCurrentUser()

  const email = isGuest
    ? guest?.anonymous_name || "Guest Session"
    : user?.email || (loading ? "Loading…" : "Not signed in")
  const fullName = isGuest ? "Demo Mode" : user?.full_name?.trim() || null
  const title = isGuest ? "Guest Session" : "Platform Dashboard"

  const handleLogout = async () => {
    if (isGuest) {
      clearGuestSessionLocal()
      router.push("/")
      return
    }
    await apiLogout(true)
    router.push("/login")
  }

  return (
    <>
      <motion.header
        initial={{ y: -60 }}
        animate={{ y: 0 }}
        className="border-b border-border bg-card/50 backdrop-blur sticky top-0 z-40"
        data-testid="top-bar"
        data-auth-mode={isGuest ? "guest" : user ? "user" : "anonymous"}
      >
        <div className="px-8 py-3 flex justify-between items-center md:pl-8 pl-14 gap-4">
          <div className="min-w-0 flex items-center gap-3">
            <h2 className="text-lg font-semibold text-balance truncate">{title}</h2>
            {isGuest ? (
              <span
                className="shrink-0 rounded bg-amber-400/15 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-amber-200/90 border border-amber-500/30"
                data-testid="demo-mode-pill"
              >
                Demo Mode
              </span>
            ) : null}
          </div>
          <div className="flex items-center gap-4">
            {isGuest ? (
              <button
                type="button"
                onClick={() => router.push("/login?next=/dashboard")}
                className="hidden sm:inline-flex items-center rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-1.5 text-xs font-medium text-amber-100 hover:bg-amber-500/20"
                data-testid="topbar-upgrade"
              >
                Upgrade
              </button>
            ) : null}
            <motion.button
              whileHover={{ scale: 1.1 }}
              whileTap={{ scale: 0.95 }}
              type="button"
              className="relative p-2 rounded-lg hover:bg-card text-muted-foreground hover:text-foreground transition-colors"
              aria-label="Notifications"
            >
              <Bell className="w-5 h-5" />
              <span className="absolute top-1 right-1 w-2 h-2 bg-destructive rounded-full" />
            </motion.button>

            <div className="w-px h-6 bg-border" />

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  className="flex items-center gap-3 rounded-lg px-2 py-1.5 hover:bg-muted/40 transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  aria-label="Account menu"
                >
                  <div className="text-right text-sm min-w-0">
                    <p className="font-medium truncate max-w-[220px]" title={email}>
                      {email}
                    </p>
                    {fullName ? (
                      <p className="text-xs text-muted-foreground truncate max-w-[220px]">
                        {fullName}
                      </p>
                    ) : null}
                  </div>
                  <div
                    className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${
                      isGuest ? "bg-amber-500/20" : "bg-muted"
                    }`}
                  >
                    <User
                      className={`w-4 h-4 ${isGuest ? "text-amber-200" : "text-muted-foreground"}`}
                    />
                  </div>
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-72">
                <DropdownMenuLabel className="font-normal">
                  <div className="flex flex-col gap-1.5">
                    <p className="text-xs text-muted-foreground">
                      {isGuest ? "Demo session" : "Signed in as"}
                    </p>
                    <div className="flex items-start gap-2">
                      <Mail className="w-4 h-4 text-muted-foreground mt-0.5 shrink-0" />
                      <p className="text-sm font-medium text-foreground break-all">{email}</p>
                    </div>
                    {fullName ? (
                      <p className="text-xs text-muted-foreground pl-6">{fullName}</p>
                    ) : null}
                  </div>
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                {isGuest ? (
                  <DropdownMenuItem
                    onClick={() => router.push("/login?next=/dashboard")}
                    className="cursor-pointer"
                  >
                    <Settings className="w-4 h-4" />
                    Sign in to upgrade
                  </DropdownMenuItem>
                ) : (
                  <DropdownMenuItem
                    onClick={() => router.push("/settings")}
                    className="cursor-pointer"
                  >
                    <Settings className="w-4 h-4" />
                    Settings
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem
                  variant="destructive"
                  onClick={handleLogout}
                  className="cursor-pointer"
                >
                  <LogOut className="w-4 h-4" />
                  {isGuest ? "End demo" : "Log out"}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </motion.header>

      {/* Scrolls with the page — not sticky */}
      {isGuest ? (
        <div className="px-8 pt-3 md:pl-8 pl-14" data-testid="guest-session-notice">
          <GuestSessionBadge />
        </div>
      ) : null}
    </>
  )
}
