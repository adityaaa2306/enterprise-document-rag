"use client"

import { motion } from "framer-motion";
import { Radar, Gauge, FileCheck2 } from "lucide-react";

const NODES = [
  { id: "upload", label: "Upload", x: 60, y: 90 },
  { id: "parse", label: "Parse", x: 190, y: 90 },
  { id: "capability", label: "Capability", x: 320, y: 90 },
  { id: "chunk", label: "Chunk", x: 450, y: 90 },
  { id: "route", label: "Carbon route", x: 580, y: 90 },
  { id: "tiers", label: "Model tiers", x: 710, y: 90 },
  { id: "validate", label: "Validate", x: 840, y: 90 },
  { id: "compile", label: "Compile", x: 970, y: 90 },
];

/** Compact labels for the 4×2 mobile grid */
const MOBILE_LABELS = {
  upload: "Upload",
  parse: "Parse",
  capability: "Capability",
  chunk: "Chunk",
  route: "Route",
  tiers: "Tiers",
  validate: "Validate",
  compile: "Compile",
};

const CARDS = [
  {
    icon: Radar,
    title: "Adaptive routing",
    body: "Per-chunk complexity analysis selects the smallest sufficient model.",
  },
  {
    icon: Gauge,
    title: "Carbon-aware scheduling",
    body: "Live grid intensity biases routing toward lighter tiers when carbon is high.",
  },
  {
    icon: FileCheck2,
    title: "Transparent accounting",
    body: "Every gram is derived from measured tokens · J/token · grid — never estimated.",
  },
];

function MobileNodeGrid() {
  const row1 = NODES.slice(0, 4);
  const row2 = NODES.slice(4);

  return (
    <div className="md:hidden p-3 sm:p-4" data-testid="system-flow-mobile">
      <div className="grid grid-cols-4 gap-1.5 sm:gap-2">
        {row1.map((n, i) => (
          <motion.div
            key={n.id}
            initial={{ opacity: 0, y: 8 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ delay: i * 0.06, duration: 0.4 }}
            className="relative flex flex-col items-center"
          >
            <div className="w-full border border-white/20 bg-[#0a0a0a] px-1 py-2.5 sm:py-3 text-center min-h-[44px] flex items-center justify-center">
              <span className="font-mono text-[8px] sm:text-[9px] uppercase tracking-[0.08em] text-neutral-200 leading-tight">
                {MOBILE_LABELS[n.id] || n.label}
              </span>
            </div>
            <span className="mt-1 font-mono text-[8px] tracking-[0.14em] text-neutral-600">
              {String(i + 1).padStart(2, "0")}
            </span>
            {i < row1.length - 1 && (
              <span
                aria-hidden
                className="pointer-events-none absolute top-[22px] -right-[calc(0.375rem+1px)] sm:-right-[calc(0.5rem+1px)] w-[calc(0.75rem+2px)] sm:w-[calc(1rem+2px)] h-px border-t border-dashed border-white/20"
              />
            )}
          </motion.div>
        ))}
      </div>

      {/* Row connector */}
      <div className="flex justify-end pr-[12.5%] my-1" aria-hidden>
        <div className="h-4 w-px border-l border-dashed border-white/20" />
      </div>

      <div className="grid grid-cols-4 gap-1.5 sm:gap-2">
        {row2.map((n, i) => (
          <motion.div
            key={n.id}
            initial={{ opacity: 0, y: 8 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ delay: 0.25 + i * 0.06, duration: 0.4 }}
            className="relative flex flex-col items-center"
          >
            <div className="w-full border border-white/20 bg-[#0a0a0a] px-1 py-2.5 sm:py-3 text-center min-h-[44px] flex items-center justify-center">
              <span className="font-mono text-[8px] sm:text-[9px] uppercase tracking-[0.08em] text-neutral-200 leading-tight">
                {MOBILE_LABELS[n.id] || n.label}
              </span>
            </div>
            <span className="mt-1 font-mono text-[8px] tracking-[0.14em] text-neutral-600">
              {String(i + 5).padStart(2, "0")}
            </span>
            {i < row2.length - 1 && (
              <span
                aria-hidden
                className="pointer-events-none absolute top-[22px] -right-[calc(0.375rem+1px)] sm:-right-[calc(0.5rem+1px)] w-[calc(0.75rem+2px)] sm:w-[calc(1rem+2px)] h-px border-t border-dashed border-white/20"
              />
            )}
          </motion.div>
        ))}
      </div>
    </div>
  );
}

export default function SystemOverview() {
  return (
    <section id="system" data-testid="system-overview" className="relative py-16 sm:py-24 md:py-32 hairline-t bg-[#070707]">
      <div className="max-w-[1400px] mx-auto px-4 sm:px-6 md:px-10">
        <div className="flex items-baseline justify-between mb-10 sm:mb-16">
          <div>
            <div className="font-mono text-[10px] uppercase tracking-[0.24em] text-neutral-500 mb-2">
              System overview
            </div>
            <h2 className="font-display text-[clamp(1.5rem,5vw,3rem)] md:text-5xl tracking-tight text-white">
              Eight nodes, one <span className="italic font-serif font-light text-emerald-400">decision</span> loop.
            </h2>
          </div>
          <div className="hidden md:block font-mono text-[10px] uppercase tracking-[0.2em] text-neutral-600">
            fig. 02
          </div>
        </div>

        {/* Diagram */}
        <div className="border border-white/10 bg-[#080808] overflow-hidden">
          <div className="hairline-b px-4 sm:px-5 py-3 flex items-center justify-between font-mono text-[10px] uppercase tracking-[0.2em] text-neutral-500">
            <span>architecture / linear-flow</span>
            <span className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 bg-emerald-400 rounded-full animate-pulse" />
              live
            </span>
          </div>

          {/* Mobile: 4 top + 4 bottom — all nodes visible without horizontal scroll */}
          <MobileNodeGrid />

          {/* Desktop / tablet: original linear SVG */}
          <div className="hidden md:block overflow-x-auto">
            <svg viewBox="0 0 1030 180" className="w-full min-w-[900px] h-[220px]">
              {NODES.map((n, i) => {
                if (i === NODES.length - 1) return null;
                const next = NODES[i + 1];
                return (
                  <motion.line
                    key={n.id}
                    x1={n.x + 50} y1={n.y} x2={next.x - 50} y2={next.y}
                    stroke="rgba(255,255,255,0.15)"
                    strokeWidth="1"
                    strokeDasharray="3 3"
                    initial={{ pathLength: 0 }}
                    whileInView={{ pathLength: 1 }}
                    viewport={{ once: true }}
                    transition={{ delay: i * 0.08, duration: 0.6 }}
                  />
                );
              })}
              {NODES.map((n, i) => (
                <motion.g
                  key={n.id}
                  initial={{ opacity: 0, y: 10 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true }}
                  transition={{ delay: i * 0.08 + 0.2, duration: 0.5 }}
                >
                  <rect
                    x={n.x - 50} y={n.y - 22} width="100" height="44"
                    fill="#0a0a0a" stroke="rgba(255,255,255,0.2)"
                  />
                  <text
                    x={n.x} y={n.y + 4} textAnchor="middle"
                    fontFamily="JetBrains Mono, monospace" fontSize="10.5"
                    fill="#E5E5E5" style={{ letterSpacing: "0.1em", textTransform: "uppercase" }}
                  >
                    {n.label}
                  </text>
                  <text
                    x={n.x} y={n.y + 46} textAnchor="middle"
                    fontFamily="JetBrains Mono, monospace" fontSize="9"
                    fill="#525252" style={{ letterSpacing: "0.14em" }}
                  >
                    {String(i + 1).padStart(2, "0")}
                  </text>
                </motion.g>
              ))}
            </svg>
          </div>
        </div>

        {/* Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-8 sm:mt-12">
          {CARDS.map((c, i) => {
            const Icon = c.icon;
            return (
              <motion.div
                key={c.title}
                data-testid={`overview-card-${i}`}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.1, duration: 0.6 }}
                className="group relative border border-white/10 bg-[#080808] p-6 sm:p-8 hover:border-emerald-500/40 transition-colors"
              >
                <div className="flex items-center justify-between mb-6 sm:mb-8">
                  <Icon className="w-6 h-6 text-emerald-400" strokeWidth={1.4} />
                  <span className="font-serif italic text-3xl text-neutral-700">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                </div>
                <h3 className="font-display text-xl md:text-2xl tracking-tight text-white">{c.title}</h3>
                <p className="mt-3 text-sm text-neutral-400 leading-relaxed">{c.body}</p>
              </motion.div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
