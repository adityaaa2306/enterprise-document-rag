"use client"

import { motion } from "framer-motion";
import { ArrowUpRight } from "lucide-react";
import { LiveDemoLink } from "@/components/live-demo-link";

export default function DashboardPreview() {
  return (
    <section id="dashboard" data-testid="dashboard-preview" className="relative py-24 md:py-32 hairline-t">
      <div className="max-w-[1400px] mx-auto px-6 md:px-10">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-10 mb-12">
          <div className="lg:col-span-7">
            <div className="font-mono text-[10px] uppercase tracking-[0.24em] text-neutral-500 mb-2">
              09 · Live dashboard
            </div>
            <h2 className="font-display text-3xl md:text-5xl tracking-tight text-white leading-[1.05]">
              Every gram, <span className="italic font-serif font-light text-emerald-400">accounted.</span>
            </h2>
          </div>
          <div className="lg:col-span-5 flex items-end justify-start lg:justify-end">
            <LiveDemoLink
              data-testid="dashboard-cta"
              className="group inline-flex items-center gap-2 bg-emerald-500 text-black px-5 py-3 font-mono text-[11px] uppercase tracking-[0.18em] hover:bg-emerald-400 transition-colors emerald-glow"
            >
              View live demo
              <ArrowUpRight className="w-3.5 h-3.5 group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition-transform" strokeWidth={2} />
            </LiveDemoLink>
          </div>
        </div>

        <motion.div
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1] }}
          className="border border-white/10 bg-[#080808] overflow-hidden"
        >
          {/* browser chrome */}
          <div className="hairline-b flex items-center gap-3 px-4 py-3 bg-[#0a0a0a]">
            <div className="flex gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-rose-500/70" />
              <span className="w-2.5 h-2.5 rounded-full bg-amber-500/70" />
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-500/70" />
            </div>
            <div className="ml-4 flex-1 flex items-center gap-2 font-mono text-[11px] text-neutral-500 bg-[#141414] px-3 py-1.5 max-w-md">
              <span className="text-neutral-600">▲</span>
              green-agentic.systems/dashboard/run/4c8a
            </div>
            <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.14em] text-emerald-400">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              live
            </div>
          </div>

          {/* Dashboard body — schematic */}
          <div className="grid grid-cols-12 gap-4 p-6 md:p-8">
            {/* KPI row */}
            {[
              { label: "CO₂ saved", value: "52.1%", accent: "#10B981" },
              { label: "chunks routed", value: "5" },
              { label: "avg latency", value: "24 ms" },
              { label: "grid intensity", value: "480 g" },
            ].map((kpi, i) => (
              <div key={i} className="col-span-6 md:col-span-3 border border-white/10 p-4">
                <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-neutral-500">{kpi.label}</div>
                <div className="font-display text-2xl mt-1" style={{ color: kpi.accent || "#FAFAFA" }}>{kpi.value}</div>
              </div>
            ))}

            {/* chart placeholder */}
            <div className="col-span-12 md:col-span-8 border border-white/10 p-4 h-64 relative overflow-hidden">
              <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-neutral-500 mb-3">
                CO₂ per chunk · last run
              </div>
              <svg viewBox="0 0 400 180" className="w-full h-[calc(100%-1.5rem)]">
                {Array.from({ length: 8 }).map((_, i) => (
                  <line key={i} x1={0} y1={i * 25} x2={400} y2={i * 25} stroke="rgba(255,255,255,0.04)" />
                ))}
                {[40, 90, 30, 140, 20, 110, 55, 25].map((h, i) => {
                  const color = h > 100 ? "#F43F5E" : h > 60 ? "#F59E0B" : "#14B8A6";
                  return (
                    <motion.rect
                      key={i}
                      x={20 + i * 46} y={180 - h - 10} width={30}
                      initial={{ height: 0, y: 170 }}
                      whileInView={{ height: h, y: 180 - h - 10 }}
                      viewport={{ once: true }}
                      transition={{ delay: i * 0.06, duration: 0.6 }}
                      fill={color}
                    />
                  );
                })}
              </svg>
            </div>

            {/* Tier breakdown */}
            <div className="col-span-12 md:col-span-4 border border-white/10 p-4">
              <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-neutral-500 mb-4">
                Tier distribution
              </div>
              {[
                { t: "Light", pct: 55, c: "#14B8A6" },
                { t: "Medium", pct: 30, c: "#F59E0B" },
                { t: "Heavy", pct: 15, c: "#F43F5E" },
              ].map((row) => (
                <div key={row.t} className="mb-3">
                  <div className="flex justify-between font-mono text-[11px] mb-1">
                    <span className="text-neutral-300">{row.t}</span>
                    <span className="text-neutral-500">{row.pct}%</span>
                  </div>
                  <div className="h-1 bg-white/5">
                    <motion.div
                      initial={{ width: 0 }}
                      whileInView={{ width: `${row.pct}%` }}
                      viewport={{ once: true }}
                      transition={{ duration: 0.8 }}
                      className="h-full"
                      style={{ background: row.c }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  );
}
