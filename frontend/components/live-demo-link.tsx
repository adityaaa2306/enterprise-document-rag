"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useEffect, type ComponentProps, type MouseEvent, type ReactNode } from "react"
import { getAccessToken } from "@/lib/api"
import { ensureGuestSession, getGuestSessionId } from "@/lib/guest-session"

type Props = {
  children: ReactNode
  className?: string
  "data-testid"?: string
  /** Where to land after guest/auth is ready. Default: new job. */
  nextPath?: string
} & Omit<ComponentProps<typeof Link>, "href" | "prefetch">

/**
 * Live Demo / Try Demo CTA.
 * Creates a guest session (no login) and routes into the app.
 * Authed users / existing guests navigate immediately (session touch in background).
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
    router.prefetch("/login")
  }, [router, nextPath])

  const handleClick = async (e: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(e)
    if (e.defaultPrevented) return
    e.preventDefault()
    try {
      // Instant path: already have owner identity
      if (getAccessToken() || getGuestSessionId()) {
        router.push(nextPath)
        if (!getAccessToken()) {
          void ensureGuestSession().catch(() => undefined)
        }
        return
      }
      // Warm navigation while session creates (feels instant)
      router.prefetch(nextPath)
      await ensureGuestSession()
      router.push(nextPath)
    } catch (err) {
      console.error("[Guest] Live Demo failed", err)
      window.alert(
        "Could not start a guest demo session. Check that the API is running, then retry.",
      )
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
