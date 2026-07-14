"use client"

import { motion } from "framer-motion"
import { useEffect, useState } from "react"
import { usePathname, useRouter } from "next/navigation"
import Link from "next/link"
import {
  BarChart3,
  ChevronLeft,
  ChevronRight,
  FileText,
  LogOut,
  Settings,
  Zap,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { apiLogout } from "@/lib/api"
import { getLastJobId } from "@/lib/job-session"

const COLLAPSED_KEY = "gar_sidebar_collapsed"

export function Sidebar() {
  const pathname = usePathname()
  const router = useRouter()
  const [resultsHref, setResultsHref] = useState("/results")
  const [collapsed, setCollapsed] = useState(false)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    try {
      setCollapsed(localStorage.getItem(COLLAPSED_KEY) === "1")
    } catch {
      /* ignore */
    }
    setReady(true)
  }, [])

  useEffect(() => {
    const last = getLastJobId()
    setResultsHref(last ? `/results?job_id=${last}` : "/results")
  }, [pathname])

  const toggleCollapsed = () => {
    setCollapsed((prev) => {
      const next = !prev
      try {
        localStorage.setItem(COLLAPSED_KEY, next ? "1" : "0")
      } catch {
        /* ignore */
      }
      return next
    })
  }

  const navItems = [
    { href: "/", label: "Home", icon: Zap, match: "/" },
    { href: "/dashboard", label: "Dashboard", icon: BarChart3, match: "/dashboard" },
    { href: "/new-job", label: "New Job", icon: FileText, match: "/new-job" },
    { href: resultsHref, label: "Results", icon: BarChart3, match: "/results" },
    { href: "/settings", label: "Settings", icon: Settings, match: "/settings" },
  ]

  const handleLogout = async () => {
    await apiLogout(true)
    router.push("/login")
  }

  return (
    <motion.aside
      initial={false}
      animate={{ width: collapsed ? 72 : 256 }}
      transition={{ type: "spring", stiffness: 320, damping: 32 }}
      className={cn(
        "bg-card border-r border-border min-h-screen sticky top-0 flex flex-col shrink-0 overflow-hidden",
        !ready && "w-64",
      )}
    >
      <div className={cn("border-b border-border", collapsed ? "p-3" : "p-6")}>
        <div className={cn("flex items-center", collapsed ? "justify-center" : "gap-2 mb-2")}>
          <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center shrink-0">
            <Zap className="w-5 h-5 text-primary-foreground" />
          </div>
          {!collapsed && (
            <h1 className="text-lg font-bold leading-tight truncate">Sustainability Manager</h1>
          )}
        </div>
        {!collapsed && (
          <p className="text-xs text-muted-foreground">Smart Routing · Document Intelligence</p>
        )}
      </div>

      <div className={cn("px-2 pt-2", collapsed ? "flex justify-center" : "px-4")}>
        <button
          type="button"
          onClick={toggleCollapsed}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand" : "Collapse"}
          className="inline-flex items-center justify-center h-8 w-8 rounded-lg text-muted-foreground hover:bg-card/80 hover:text-foreground transition-colors"
        >
          {collapsed ? (
            <ChevronRight className="w-4 h-4" />
          ) : (
            <ChevronLeft className="w-4 h-4" />
          )}
        </button>
      </div>

      <nav className={cn("space-y-2 flex-1", collapsed ? "p-2" : "p-4 pt-2")}>
        {navItems.map((item) => {
          const Icon = item.icon
          const isActive =
            item.match === "/"
              ? pathname === "/"
              : pathname === item.match || pathname.startsWith(item.match + "/")

          return (
            <motion.div
              key={item.label}
              whileHover={collapsed ? undefined : { x: 4 }}
              whileTap={{ scale: 0.98 }}
            >
              <Link
                href={item.href}
                title={item.label}
                className={cn(
                  "flex items-center rounded-lg transition-colors",
                  collapsed ? "justify-center px-0 py-3" : "gap-3 px-4 py-3",
                  isActive
                    ? "bg-primary/20 text-primary font-medium"
                    : "text-muted-foreground hover:bg-card/50",
                )}
              >
                <Icon className="w-5 h-5 shrink-0" />
                {!collapsed && <span className="truncate">{item.label}</span>}
                {!collapsed && isActive && (
                  <motion.div
                    layoutId="active-indicator"
                    className="ml-auto w-1 h-6 bg-primary rounded"
                  />
                )}
              </Link>
            </motion.div>
          )
        })}
      </nav>

      <div className={cn("border-t border-border", collapsed ? "p-2" : "p-4")}>
        <button
          type="button"
          onClick={handleLogout}
          title="Log out"
          className={cn(
            "flex w-full items-center rounded-lg text-muted-foreground hover:bg-card/50 transition-colors",
            collapsed ? "justify-center px-0 py-3" : "gap-3 px-4 py-3",
          )}
        >
          <LogOut className="w-5 h-5 shrink-0" />
          {!collapsed && <span>Log out</span>}
        </button>
      </div>
    </motion.aside>
  )
}
