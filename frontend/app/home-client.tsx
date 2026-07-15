"use client"

import dynamic from "next/dynamic"
import { useEffect } from "react"
import { useRouter } from "next/navigation"
import SmoothScroll from "@/components/site/SmoothScroll"
import Nav from "@/components/site/Nav"
import Hero from "@/components/site/Hero"
import Ticker from "@/components/site/Ticker"

/** Below-fold sections — loaded after first paint so Live Demo stays snappy. */
const Problem = dynamic(() => import("@/components/site/Problem"), { ssr: false })
const SystemOverview = dynamic(() => import("@/components/site/SystemOverview"), {
  ssr: false,
})
const Pipeline = dynamic(() => import("@/components/site/Pipeline"), { ssr: false })
const CarbonRouting = dynamic(() => import("@/components/site/CarbonRouting"), {
  ssr: false,
})
const RegionScheduling = dynamic(() => import("@/components/site/RegionScheduling"), {
  ssr: false,
})
const Validation = dynamic(() => import("@/components/site/Validation"), { ssr: false })
const Methodology = dynamic(() => import("@/components/site/Methodology"), {
  ssr: false,
})
const DashboardPreview = dynamic(() => import("@/components/site/DashboardPreview"), {
  ssr: false,
})
const Benchmarks = dynamic(() => import("@/components/site/Benchmarks"), {
  ssr: false,
})
const Stack = dynamic(() => import("@/components/site/Stack"), { ssr: false })
const Research = dynamic(() => import("@/components/site/Research"), { ssr: false })
const FAQ = dynamic(() => import("@/components/site/FAQ"), { ssr: false })
const Closing = dynamic(() => import("@/components/site/Closing"), { ssr: false })
const Footer = dynamic(() => import("@/components/site/Footer"), { ssr: false })

function PrefetchCriticalRoutes() {
  const router = useRouter()
  useEffect(() => {
    const idle =
      typeof window !== "undefined" && "requestIdleCallback" in window
        ? window.requestIdleCallback.bind(window)
        : (cb: IdleRequestCallback) =>
            window.setTimeout(() => cb({ didTimeout: false, timeRemaining: () => 0 } as IdleDeadline), 200)
    const id = idle(() => {
      router.prefetch("/dashboard")
      router.prefetch("/new-job")
      router.prefetch("/login")
      router.prefetch("/results")
      router.prefetch("/settings")
      router.prefetch("/signup")
    })
    return () => {
      if (typeof window !== "undefined" && "cancelIdleCallback" in window) {
        window.cancelIdleCallback(id as number)
      } else {
        clearTimeout(id as number)
      }
    }
  }, [router])
  return null
}

export default function HomeClient() {
  return (
    <SmoothScroll>
      <div className="landing-root bg-[#050505] text-white min-h-screen">
        <div className="noise" aria-hidden="true" />
        <PrefetchCriticalRoutes />
        <main data-testid="home-root" className="relative">
          <Nav />
          <Hero />
          <Ticker />
          <Problem />
          <SystemOverview />
          <Pipeline />
          <CarbonRouting />
          <RegionScheduling />
          <Validation />
          <Methodology />
          <DashboardPreview />
          <Benchmarks />
          <Stack />
          <Research />
          <FAQ />
          <Closing />
          <Footer />
        </main>
      </div>
    </SmoothScroll>
  )
}
