"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useEffect, type ComponentProps, type MouseEvent, type ReactNode } from "react"
import { getAccessToken } from "@/lib/api"
import { ensureGuestSession } from "@/lib/guest-session"

type Props = {
  children: ReactNode
  className?: string
  "data-testid"?: string
  /** Where to land after click. Default: new job. */
  nextPath?: string
} & Omit<ComponentProps<typeof Link>, "href" | "prefetch">

/**
 * Live Demo / Try Demo CTA.
 * Navigates immediately — never awaits networking.
 * Guest session create/resume runs in the background (and in GuestOwnerGate).
 */
export function LiveDemoLink({
  children,
  className,
  onClick,
  nextPath = "/new-job",
  ...rest
}: Props) {
  const router = useRouter()

  useEffect(() => {
    router.prefetch(nextPath)
    router.prefetch("/new-job")
    router.prefetch("/dashboard")
    router.prefetch("/results")
    router.prefetch("/settings")
    router.prefetch("/login")
  }, [router, nextPath])

  const handleClick = (e: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(e)
    if (e.defaultPrevented) return
    e.preventDefault()
    // Navigation must never wait on networking
    router.push(nextPath)
    // Race ahead of GuestOwnerGate mount (single-flight dedupes with gate/prewarm)
    if (!getAccessToken()) {
      void ensureGuestSession().catch(() => undefined)
    }
  }

  return (
    <Link
      href={nextPath}
      prefetch
      className={className}
      onClick={handleClick}
      {...rest}
    >
      {children}
    </Link>
  )
}
