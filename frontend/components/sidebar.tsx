"use client"

import { useEffect, useState } from "react"
import { usePathname, useRouter } from "next/navigation"
import Link from "next/link"
import {
  BarChart3,
  FileText,
  FlaskConical,
  HelpCircle,
  Home,
  LayoutDashboard,
  LogOut,
  Menu,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  X,
  Zap,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { apiLogout, getAccessToken } from "@/lib/api"
import { getLastJobId } from "@/lib/job-session"
import { clearGuestSessionLocal, isGuestMode } from "@/lib/guest-session"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

const COLLAPSED_KEY = "gar_sidebar_collapsed"
const EXPANDED_W = 220
const COLLAPSED_W = 68

type NavItem = {
  href: string
  label: string
  icon: React.ComponentType<{ className?: string }>
  match: string
}

function NavLink({
  item,
  collapsed,
  isActive,
}: {
  item: NavItem
  collapsed: boolean
  isActive: boolean
}) {
  const Icon = item.icon
  const link = (
    <Link
      href={item.href}
      aria-label={item.label}
      aria-current={isActive ? "page" : undefined}
      className={cn(
        "group relative flex items-center rounded-lg outline-none transition-all duration-200",
        "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        collapsed ? "justify-center h-10 w-10 mx-auto" : "gap-3 px-3 py-2.5",
        isActive
          ? "bg-emerald-500/15 text-emerald-300 font-semibold"
          : "text-muted-foreground hover:bg-white/[0.04] hover:text-foreground",
      )}
    >
      {isActive && !collapsed ? (
        <span className="absolute left-0 top-1/2 -translate-y-1/2 h-5 w-[3px] rounded-r-full bg-emerald-400" />
      ) : null}
      {isActive && collapsed ? (
        <span className="absolute inset-0 rounded-lg ring-1 ring-emerald-400/40" />
      ) : null}
      <Icon
        className={cn(
          "w-[18px] h-[18px] shrink-0 transition-colors duration-200",
          isActive ? "text-emerald-400" : "group-hover:text-foreground",
        )}
      />
      <span
        className={cn(
          "text-sm whitespace-nowrap transition-all duration-300 ease-in-out",
          collapsed
            ? "max-w-0 opacity-0 overflow-hidden"
            : "max-w-[140px] opacity-100",
        )}
      >
        {item.label}
      </span>
    </Link>
  )

  if (!collapsed) return link

  return (
    <Tooltip delayDuration={100}>
      <TooltipTrigger asChild>{link}</TooltipTrigger>
      <TooltipContent side="right" sideOffset={8}>
        {item.label}
      </TooltipContent>
    </Tooltip>
  )
}

export function Sidebar() {
  const pathname = usePathname()
  const router = useRouter()
  const [resultsHref, setResultsHref] = useState("/results")
  const [collapsed, setCollapsed] = useState(false)
  const [ready, setReady] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [guestDemo, setGuestDemo] = useState(false)

  useEffect(() => {
    try {
      setCollapsed(localStorage.getItem(COLLAPSED_KEY) === "1")
    } catch {
      /* ignore */
    }
    setGuestDemo(isGuestMode())
    setReady(true)
  }, [])

  useEffect(() => {
    const last = getLastJobId()
    setResultsHref(last ? `/results?job_id=${last}` : "/results")
  }, [pathname])

  useEffect(() => {
    setMobileOpen(false)
  }, [pathname])

  // Prefetch app shell routes so sidebar navigation feels native.
  useEffect(() => {
    const routes = [
      "/dashboard",
      "/new-job",
      "/results",
      "/benchmarks",
      "/settings",
      "/login",
    ]
    for (const r of routes) {
      try {
        router.prefetch(r)
      } catch {
        /* ignore */
      }
    }
    const last = getLastJobId()
    if (last) {
      try {
        router.prefetch(`/results?job_id=${last}`)
      } catch {
        /* ignore */
      }
    }
    // Warm shared metrics cache in background (Dashboard/Results parity).
    void import("@/lib/finalized-metrics-store").then((m) =>
      m.ensureFinalizedMetrics().catch(() => undefined),
    )
  }, [router])

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

  const primaryNav: NavItem[] = [
    { href: "/", label: "Home", icon: Home, match: "/" },
    { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard, match: "/dashboard" },
    { href: "/new-job", label: "New Job", icon: FileText, match: "/new-job" },
    { href: resultsHref, label: "Results", icon: BarChart3, match: "/results" },
    {
      href: "/benchmarks",
      label: "Benchmarks",
      icon: FlaskConical,
      match: "/benchmarks",
    },
  ]

  const handleLogout = async () => {
    if (guestDemo || isGuestMode() || !getAccessToken()) {
      clearGuestSessionLocal()
      router.push("/")
      return
    }
    await apiLogout(true)
    router.push("/login")
  }

  const width = collapsed ? COLLAPSED_W : EXPANDED_W

  const asideInner = (
    <>
      {/* Brand header + toggle */}
      <div
        className={cn(
          "border-b border-border/80 shrink-0",
          collapsed ? "px-2 py-4" : "px-4 py-5",
        )}
      >
        <div className={cn("flex items-start", collapsed ? "flex-col items-center gap-3" : "gap-3")}>
          <div className="w-9 h-9 rounded-lg bg-emerald-500/15 border border-emerald-500/25 flex items-center justify-center shrink-0">
            <Zap className="w-4.5 h-4.5 text-emerald-400" />
          </div>
          <div
            className={cn(
              "min-w-0 flex-1 transition-all duration-300 ease-in-out",
              collapsed ? "max-h-0 opacity-0 overflow-hidden w-0" : "max-h-20 opacity-100",
            )}
          >
            <p className="text-[15px] font-semibold leading-snug tracking-tight text-foreground">
              Green Agentic
            </p>
            <p className="text-[11px] text-muted-foreground leading-snug mt-0.5">
              Document Intelligence
            </p>
          </div>
          <button
            type="button"
            onClick={toggleCollapsed}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className={cn(
              "hidden md:inline-flex items-center justify-center h-8 w-8 rounded-md",
              "text-muted-foreground hover:text-foreground hover:bg-white/[0.06]",
              "transition-colors duration-200 outline-none focus-visible:ring-2 focus-visible:ring-ring",
              collapsed && "mt-0",
            )}
          >
            {collapsed ? (
              <PanelLeftOpen className="w-4 h-4" />
            ) : (
              <PanelLeftClose className="w-4 h-4" />
            )}
          </button>
          <button
            type="button"
            className="md:hidden inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-white/[0.06]"
            onClick={() => setMobileOpen(false)}
            aria-label="Close menu"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Primary nav */}
      <nav
        className={cn(
          "flex-1 overflow-y-auto py-3",
          collapsed ? "px-2 space-y-1.5" : "px-3 space-y-1",
        )}
      >
        {!collapsed && (
          <p className="px-3 pb-2 text-[10px] font-medium uppercase tracking-[0.12em] text-muted-foreground/70">
            Navigate
          </p>
        )}
        {primaryNav.map((item) => {
          const isActive =
            item.match === "/"
              ? pathname === "/"
              : pathname === item.match || pathname.startsWith(item.match + "/")
          return (
            <NavLink
              key={item.label}
              item={item}
              collapsed={collapsed}
              isActive={isActive}
            />
          )
        })}
      </nav>

      {/* Bottom pinned */}
      <div
        className={cn(
          "mt-auto border-t border-border/80 shrink-0",
          collapsed ? "px-2 py-3 space-y-1.5" : "px-3 py-3 space-y-1",
        )}
      >
        <NavLink
          item={{
            href: "/settings",
            label: "Settings",
            icon: Settings,
            match: "/settings",
          }}
          collapsed={collapsed}
          isActive={pathname === "/settings" || pathname.startsWith("/settings/")}
        />

        {!collapsed && (
          <div className="px-1 pt-1 space-y-0.5">
            <button
              type="button"
              disabled
              className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted-foreground/50 cursor-not-allowed"
              title="Coming soon"
            >
              <HelpCircle className="w-[18px] h-[18px]" />
              Help
            </button>
            <button
              type="button"
              disabled
              className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted-foreground/50 cursor-not-allowed"
              title="Coming soon"
            >
              <MessageSquare className="w-[18px] h-[18px]" />
              Feedback
            </button>
          </div>
        )}

        <Tooltip delayDuration={100}>
          <TooltipTrigger asChild>
            <button
              type="button"
              onClick={handleLogout}
              aria-label="Log out"
              className={cn(
                "flex w-full items-center rounded-lg text-muted-foreground",
                "hover:bg-white/[0.04] hover:text-foreground transition-colors duration-200",
                "outline-none focus-visible:ring-2 focus-visible:ring-ring",
                collapsed ? "justify-center h-10 w-10 mx-auto" : "gap-3 px-3 py-2.5",
              )}
            >
              <LogOut className="w-[18px] h-[18px] shrink-0" />
              {!collapsed && (
                <span className="text-sm">
                  {guestDemo ? "End demo" : "Log out"}
                </span>
              )}
            </button>
          </TooltipTrigger>
          {collapsed ? (
            <TooltipContent side="right" sideOffset={8}>
              Log out
            </TooltipContent>
          ) : null}
        </Tooltip>

        {!collapsed && (
          <p className="px-3 pt-2 text-[10px] text-muted-foreground/60 tracking-wide">
            Research Preview · v1.0
          </p>
        )}
      </div>
    </>
  )

  return (
    <>
      {/* Mobile open button */}
      <button
        type="button"
        className="md:hidden fixed top-3 left-3 z-50 inline-flex h-9 w-9 items-center justify-center rounded-lg border border-border bg-card/95 text-foreground shadow-sm"
        onClick={() => setMobileOpen(true)}
        aria-label="Open menu"
      >
        <Menu className="w-4 h-4" />
      </button>

      {/* Mobile overlay drawer */}
      <div
        className={cn(
          "md:hidden fixed inset-0 z-50 transition-opacity duration-300",
          mobileOpen ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none",
        )}
      >
        <button
          type="button"
          className="absolute inset-0 bg-black/60"
          aria-label="Close menu overlay"
          onClick={() => setMobileOpen(false)}
        />
        <aside
          className={cn(
            "absolute left-0 top-0 h-full w-[220px] bg-card border-r border-border flex flex-col",
            "transition-transform duration-[350ms] ease-in-out",
            mobileOpen ? "translate-x-0" : "-translate-x-full",
          )}
        >
          {asideInner}
        </aside>
      </div>

      {/* Desktop persistent sidebar */}
      <aside
        style={{ width: ready ? width : EXPANDED_W }}
        className={cn(
          "hidden md:flex flex-col shrink-0 sticky top-0 h-screen",
          "bg-card border-r border-border overflow-hidden",
          "transition-[width] duration-[350ms] ease-in-out",
        )}
      >
        {asideInner}
      </aside>
    </>
  )
}
