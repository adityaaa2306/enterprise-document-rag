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

export function TopBar() {
  const router = useRouter()
  const { user, loading } = useCurrentUser()

  // Always prefer the signed-in email in the header — never the product name.
  const email = user?.email || (loading ? "Loading…" : "Not signed in")
  const fullName = user?.full_name?.trim() || null

  const handleLogout = async () => {
    await apiLogout(true)
    router.push("/login")
  }

  return (
    <motion.header
      initial={{ y: -60 }}
      animate={{ y: 0 }}
      className="border-b border-border bg-card/50 backdrop-blur sticky top-0 z-40"
    >
      <div className="px-8 py-4 flex justify-between items-center md:pl-8 pl-14">
        <h2 className="text-xl font-semibold text-balance">Platform Dashboard</h2>

        <div className="flex items-center gap-4">
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
                <div className="w-8 h-8 rounded-full bg-muted flex items-center justify-center shrink-0">
                  <User className="w-4 h-4 text-muted-foreground" />
                </div>
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-72">
              <DropdownMenuLabel className="font-normal">
                <div className="flex flex-col gap-1.5">
                  <p className="text-xs text-muted-foreground">Signed in as</p>
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
              <DropdownMenuItem
                onClick={() => router.push("/settings")}
                className="cursor-pointer"
              >
                <Settings className="w-4 h-4" />
                Settings
              </DropdownMenuItem>
              <DropdownMenuItem
                variant="destructive"
                onClick={handleLogout}
                className="cursor-pointer"
              >
                <LogOut className="w-4 h-4" />
                Log out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </motion.header>
  )
}
