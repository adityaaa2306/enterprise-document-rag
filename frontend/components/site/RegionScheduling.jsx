"use client"

import { motion, useScroll, useTransform } from "framer-motion";
import { useRef } from "react";

const REGIONS = [
  { id: "us-west-2",  name: "us-west-2",  x: 130, y: 210, grid: 210, tier: "primary", city: "Oregon" },
  { id: "us-east-1",  name: "us-east-1",  x: 320, y: 230, grid: 420, tier: "reference", city: "Virginia" },
  { id: "eu-north-1", name: "eu-north-1", x: 560, y: 140, grid: 45,  tier: "reference", city: "Stockholm" },
  { id: "eu-west-1",  name: "eu-west-1",  x: 500, y: 200, grid: 290, tier: "reference", city: "Ireland" },
  { id: "ap-south-1", name: "ap-south-1", x: 760, y: 270, grid: 710, tier: "reference", city: "Mumbai" },
  { id: "ap-ne-1",    name: "ap-ne-1",    x: 880, y: 210, grid: 480, tier: "reference", city: "Tokyo" },
];

export default function RegionScheduling() {
  const ref = useRef(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start end", "end start"] });
  const y = useTransform(scrollYProgress, [0, 1], [40, -40]);

  return (
    <section id="regions" data-testid="regions-section" className="relative py-24 md:py-32 hairline-t">
      <div className="max-w-[1400px] mx-auto px-6 md:px-10">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-10 mb-12">
          <div className="lg:col-span-7">
            <div className="font-mono text-[10px] uppercase tracking-[0.24em] text-neutral-500 mb-2">
              06 · Region scheduling
            </div>
            <h2 className="font-display text-3xl md:text-5xl tracking-tight text-white leading-[1.05]">
              Follow the <span className="italic font-serif font-light text-emerald-400">clean grid.</span>
            </h2>
          </div>
          <div className="lg:col-span-5 flex items-end">
            <p className="text-neutral-400 text-[15px] leading-relaxed">
              Multi-region execution: architecture-ready, not yet active. Candidate regions
              ranked by real-time carbon intensity from Electricity Maps.
            </p>
          </div>
        </div>

        <motion.div ref={ref} style={{ y }} className="border border-white/10 bg-[#080808]">
          <div className="hairline-b px-5 py-3 flex items-center justify-between font-mono text-[10px] uppercase tracking-[0.2em] text-neutral-500">
            <span>fig. 04 — candidate regions</span>
            <span className="text-amber-400/80">status · architecture-ready</span>
          </div>
          <div className="relative overflow-hidden">
            <svg
              viewBox="0 0 1000 420"
              className="w-full h-auto min-h-[280px] md:min-h-[360px]"
              preserveAspectRatio="xMidYMid meet"
            >
              {/* faint grid */}
              {Array.from({ length: 12 }).map((_, i) => (
                <line key={i} x1={i * 84} y1={0} x2={i * 84} y2={420} stroke="rgba(255,255,255,0.03)" />
              ))}
              {Array.from({ length: 7 }).map((_, i) => (
                <line key={"h" + i} x1={0} y1={i * 70} x2={1000} y2={i * 70} stroke="rgba(255,255,255,0.03)" />
              ))}
              {/* connecting lines to primary */}
              {REGIONS.filter((r) => r.tier === "reference").map((r) => (
                <line
                  key={"c" + r.id}
                  x1={130} y1={210} x2={r.x} y2={r.y}
                  stroke="rgba(255,255,255,0.06)"
                  strokeDasharray="3 4"
                />
              ))}
              {REGIONS.map((r, i) => {
                const isPrimary = r.tier === "primary";
                return (
                  <g key={r.id} transform={`translate(${r.x}, ${r.y})`}>
                    <motion.g
                      initial={{ opacity: 0 }}
                      whileInView={{ opacity: 1 }}
                      viewport={{ once: true }}
                      transition={{ delay: i * 0.08, duration: 0.6 }}
                    >
                      {isPrimary && (
                        <>
                          <motion.circle
                            r={26}
                            fill="none"
                            stroke="#10B981"
                            strokeWidth="0.8"
                            animate={{ r: [22, 42, 22], opacity: [0.6, 0, 0.6] }}
                            transition={{ duration: 2.4, repeat: Infinity }}
                          />
                          <circle r={18} fill="rgba(16,185,129,0.1)" stroke="#10B981" strokeWidth="1.2" />
                        </>
                      )}
                      {!isPrimary && (
                        <circle r={5} fill="#0a0a0a" stroke="rgba(255,255,255,0.35)" strokeWidth="1" />
                      )}
                      <text
                        x={0} y={isPrimary ? -34 : -16}
                        textAnchor="middle"
                        fontFamily="JetBrains Mono, monospace" fontSize="10"
                        fill={isPrimary ? "#10B981" : "#E5E5E5"}
                        style={{ letterSpacing: "0.14em", textTransform: "uppercase" }}
                      >
                        {r.name}
                      </text>
                      <text
                        x={0} y={isPrimary ? 44 : 24}
                        textAnchor="middle"
                        fontFamily="JetBrains Mono, monospace" fontSize="9"
                        fill="#525252"
                        style={{ letterSpacing: "0.12em" }}
                      >
                        {r.grid} gCO₂/kWh
                      </text>
                    </motion.g>
                  </g>
                );
              })}
            </svg>
          </div>
          <div className="hairline-t grid grid-cols-2 md:grid-cols-6 divide-x divide-white/5">
            {REGIONS.map((r) => (
              <div key={r.id} className="p-4">
                <div className="font-mono text-[10px] uppercase tracking-[0.14em]" style={{ color: r.tier === "primary" ? "#10B981" : "#A3A3A3" }}>
                  {r.name}
                </div>
                <div className="font-mono text-[11px] text-neutral-500 mt-1">{r.city}</div>
                <div className="font-mono text-[13px] text-white mt-2">{r.grid} g</div>
              </div>
            ))}
          </div>
        </motion.div>
        <p className="mt-4 font-mono text-[10px] uppercase tracking-[0.2em] text-neutral-500">
          caption · multi-region execution is architecture-ready, not yet active.
        </p>
      </div>
    </section>
  );
}
