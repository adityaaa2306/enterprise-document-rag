"use client"

import SmoothScroll from "@/components/site/SmoothScroll"
import Nav from "@/components/site/Nav"
import Hero from "@/components/site/Hero"
import Ticker from "@/components/site/Ticker"
import Problem from "@/components/site/Problem"
import SystemOverview from "@/components/site/SystemOverview"
import Pipeline from "@/components/site/Pipeline"
import CarbonRouting from "@/components/site/CarbonRouting"
import RegionScheduling from "@/components/site/RegionScheduling"
import Validation from "@/components/site/Validation"
import Methodology from "@/components/site/Methodology"
import DashboardPreview from "@/components/site/DashboardPreview"
import Benchmarks from "@/components/site/Benchmarks"
import Stack from "@/components/site/Stack"
import Research from "@/components/site/Research"
import FAQ from "@/components/site/FAQ"
import Closing from "@/components/site/Closing"
import Footer from "@/components/site/Footer"

export default function Home() {
  return (
    <SmoothScroll>
      <div className="landing-root bg-[#050505] text-white min-h-screen">
        <div className="noise" aria-hidden="true" />
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
