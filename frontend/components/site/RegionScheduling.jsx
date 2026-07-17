"use client"

import { motion, useScroll, useTransform } from "framer-motion";
import { useRef } from "react";

const REGIONS = [
  { id: "india",      name: "india",      x: 760, y: 270, grid: 640, tier: "primary", city: "India · IN-WE" },
  { id: "us-west-2",  name: "us-west-2",  x: 130, y: 210, grid: 210, tier: "reference", city: "Oregon" },
  { id: "us-east-1",  name: "us-east-1",  x: 320, y: 230, grid: 420, tier: "reference", city: "Virginia" },
  { id: "eu-north-1", name: "eu-north-1", x: 560, y: 140, grid: 45,  tier: "reference", city: "Stockholm" },
  { id: "eu-west-1",  name: "eu-west-1",  x: 500, y: 200, grid: 290, tier: "reference", city: "Ireland" },
  { id: "ap-ne-1",    name: "ap-ne-1",    x: 880, y: 210, grid: 480, tier: "reference", city: "Tokyo" },
];

/** Compact mobile map positions — 2 rows × 3, all markers readable */
const MOBILE_REGIONS = [
  { id: "india",      name: "india",      x: 250, y: 230, grid: 640, tier: "primary", city: "India · IN-WE" },
  { id: "us-west-2",  name: "us-west-2",  x: 90,  y: 90,  grid: 210, tier: "reference", city: "Oregon" },
  { id: "us-east-1",  name: "us-east-1",  x: 250, y: 100, grid: 420, tier: "reference", city: "Virginia" },
  { id: "eu-north-1", name: "eu-north-1", x: 410, y: 70,  grid: 45,  tier: "reference", city: "Stockholm" },
  { id: "eu-west-1",  name: "eu-west-1",  x: 90,  y: 210, grid: 290, tier: "reference", city: "Ireland" },
  { id: "ap-ne-1",    name: "ap-ne-1",    x: 410, y: 200, grid: 480, tier: "reference", city: "Tokyo" },
];

const PRIMARY = REGIONS.find((r) => r.tier === "primary") || REGIONS[0];
const PRIMARY_MOBILE = MOBILE_REGIONS.find((r) => r.tier === "primary") || MOBILE_REGIONS[0];

function RegionCard({ r }) {
  const isPrimary = r.tier === "primary";
  return (
    <div
      data-testid={`region-card-${r.id}`}
      className="p-3.5 sm:p-4 bg-[#080808]"
    >
      <div
        className="font-mono text-[10px] uppercase tracking-[0.14em]"
        style={{ color: isPrimary ? "#10B981" : "#A3A3A3" }}
      >
        {r.name}
      </div>
      <div className="font-mono text-[11px] text-neutral-500 mt-1">{r.city}</div>
      <div className="font-mono text-[13px] text-white mt-2">{r.grid} g</div>
      {isPrimary && (
        <div className="mt-2 font-mono text-[9px] uppercase tracking-[0.16em] text-emerald-400/80">
          primary
        </div>
      )}
    </div>
  );
}

export default function RegionScheduling() {
  const ref = useRef(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start end", "end start"] });
  const y = useTransform(scrollYProgress, [0, 1], [40, -40]);

  return (
    <section id="regions" data-testid="regions-section" className="relative py-16 sm:py-24 md:py-32 hairline-t">
      <div className="max-w-[1400px] mx-auto px-4 sm:px-6 md:px-10">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 sm:gap-10 mb-8 sm:mb-12">
          <div className="lg:col-span-7">
            <div className="font-mono text-[10px] uppercase tracking-[0.24em] text-neutral-500 mb-2">
              06 · Region scheduling
            </div>
            <h2 className="font-display text-[clamp(1.5rem,5vw,3rem)] md:text-5xl tracking-tight text-white leading-[1.05]">
              Follow the <span className="italic font-serif font-light text-emerald-400">clean grid.</span>
            </h2>
          </div>
          <div className="lg:col-span-5 flex items-end">
            <p className="text-neutral-400 text-[14px] sm:text-[15px] leading-relaxed">
              Live execution is single-region (default India) with Electricity Maps intensity for
              accounting. Multi-region carbon-optimal placement is architecture-ready — not pretended live.
            </p>
          </div>
        </div>

        <div ref={ref} className="border border-white/10 bg-[#080808]">
          <div className="hairline-b px-4 sm:px-5 py-3 flex items-center justify-between gap-3 font-mono text-[10px] uppercase tracking-[0.2em] text-neutral-500">
            <span>fig. 04 — candidate regions</span>
            <span className="text-amber-400/80 shrink-0">status · single-region live</span>
          </div>

          {/* Mobile: compact 2×3 map so every region is visible */}
          <div className="md:hidden relative" data-testid="regions-map-mobile">
            <svg
              viewBox="0 0 500 300"
              className="w-full h-auto"
              preserveAspectRatio="xMidYMid meet"
            >
              {Array.from({ length: 6 }).map((_, i) => (
                <line key={i} x1={i * 100} y1={0} x2={i * 100} y2={300} stroke="rgba(255,255,255,0.04)" />
              ))}
              {Array.from({ length: 4 }).map((_, i) => (
                <line key={"h" + i} x1={0} y1={i * 100} x2={500} y2={i * 100} stroke="rgba(255,255,255,0.04)" />
              ))}
              {MOBILE_REGIONS.filter((r) => r.tier === "reference").map((r) => (
                <line
                  key={"c" + r.id}
                  x1={PRIMARY_MOBILE.x} y1={PRIMARY_MOBILE.y} x2={r.x} y2={r.y}
                  stroke="rgba(255,255,255,0.1)"
                  strokeDasharray="3 4"
                />
              ))}
              {MOBILE_REGIONS.map((r, i) => {
                const isPrimary = r.tier === "primary";
                return (
                  <g key={r.id} transform={`translate(${r.x}, ${r.y})`}>
                    <motion.g
                      initial={{ opacity: 0 }}
                      whileInView={{ opacity: 1 }}
                      viewport={{ once: true }}
                      transition={{ delay: i * 0.08, duration: 0.5 }}
                    >
                      {isPrimary && (
                        <>
                          <motion.circle
                            r={22}
                            fill="none"
                            stroke="#10B981"
                            strokeWidth="0.8"
                            style={{ transformOrigin: "center", transformBox: "fill-box" }}
                            animate={{ scale: [0.85, 1.5, 0.85], opacity: [0.6, 0, 0.6] }}
                            transition={{ duration: 2.4, repeat: Infinity }}
                          />
                          <circle r={14} fill="rgba(16,185,129,0.12)" stroke="#10B981" strokeWidth="1.4" />
                        </>
                      )}
                      {!isPrimary && (
                        <circle r={7} fill="#0a0a0a" stroke="rgba(255,255,255,0.45)" strokeWidth="1.2" />
                      )}
                      <text
                        x={0} y={isPrimary ? -28 : -16}
                        textAnchor="middle"
                        fontFamily="JetBrains Mono, monospace" fontSize="11"
                        fill={isPrimary ? "#10B981" : "#E5E5E5"}
                        style={{ letterSpacing: "0.1em", textTransform: "uppercase" }}
                      >
                        {r.name}
                      </text>
                      <text
                        x={0} y={isPrimary ? 36 : 24}
                        textAnchor="middle"
                        fontFamily="JetBrains Mono, monospace" fontSize="10"
                        fill="#737373"
                        style={{ letterSpacing: "0.1em" }}
                      >
                        {r.grid} g
                      </text>
                    </motion.g>
                  </g>
                );
              })}
            </svg>
          </div>

          {/* Desktop map — unchanged layout */}
          <motion.div style={{ y }} className="hidden md:block relative overflow-hidden">
            <svg
              viewBox="0 0 1000 420"
              className="w-full h-auto min-h-[360px]"
              preserveAspectRatio="xMidYMid meet"
            >
              {Array.from({ length: 12 }).map((_, i) => (
                <line key={i} x1={i * 84} y1={0} x2={i * 84} y2={420} stroke="rgba(255,255,255,0.03)" />
              ))}
              {Array.from({ length: 7 }).map((_, i) => (
                <line key={"h" + i} x1={0} y1={i * 70} x2={1000} y2={i * 70} stroke="rgba(255,255,255,0.03)" />
              ))}
              {REGIONS.filter((r) => r.tier === "reference").map((r) => (
                <line
                  key={"c" + r.id}
                  x1={PRIMARY.x} y1={PRIMARY.y} x2={r.x} y2={r.y}
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
                            style={{ transformOrigin: "center", transformBox: "fill-box" }}
                            animate={{ scale: [0.85, 1.6, 0.85], opacity: [0.6, 0, 0.6] }}
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
          </motion.div>

          {/* Region cards — always visible; 2×3 on phones */}
          <div className="hairline-t grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-px bg-white/5">
            {REGIONS.map((r) => (
              <RegionCard key={r.id} r={r} />
            ))}
          </div>
        </div>
        <p className="mt-4 font-mono text-[10px] uppercase tracking-[0.2em] text-neutral-500">
          caption · primary = configured live region · dashed nodes = future multi-region candidates
        </p>
      </div>
    </section>
  );
}
