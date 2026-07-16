"use client"

import Link from "next/link";
import { motion, useScroll, useTransform } from "framer-motion";
import { useRef, useState, useEffect } from "react";
import { ArrowUpRight, ArrowRight } from "lucide-react";
import { LiveDemoLink } from "@/components/live-demo-link";

const HEADLINE_LINES = [
  "A document processing pipeline",
  "that decides, per chunk, which model",
  "to use — and measures exactly how much",
  <span key="carbon">
    carbon that decision{" "}
    <span className="italic font-serif font-light text-emerald-400">saves.</span>
  </span>,
];

const PIPELINE = [
  { id: "parse", label: "Parse", x: 50, y: 40 },
  { id: "analyze", label: "Analyze", x: 50, y: 120 },
  { id: "route", label: "Route", x: 50, y: 200 },
  { id: "light", label: "Light", x: 220, y: 280, tier: "light" },
  { id: "medium", label: "Medium", x: 50, y: 280, tier: "medium" },
  { id: "heavy", label: "Heavy", x: -120, y: 280, tier: "heavy" },
  { id: "validate", label: "Validate", x: 50, y: 360 },
  { id: "compile", label: "Compile", x: 50, y: 440 },
];

const EDGES = [
  ["parse", "analyze"],
  ["analyze", "route"],
  ["route", "light"],
  ["route", "medium"],
  ["route", "heavy"],
  ["light", "validate"],
  ["medium", "validate"],
  ["heavy", "validate"],
  ["validate", "compile"],
];

const tierColor = (t) =>
  t === "light" ? "#14B8A6" : t === "medium" ? "#F59E0B" : t === "heavy" ? "#F43F5E" : "#FAFAFA";

function NodeGraph() {
  const [active, setActive] = useState(0);
  const order = ["parse", "analyze", "route", "medium", "light", "heavy", "validate", "compile"];
  useEffect(() => {
    const t = setInterval(() => setActive((i) => (i + 1) % order.length), 900);
    return () => clearInterval(t);
  }, []);
  const activeId = order[active];
  const nodeById = Object.fromEntries(PIPELINE.map((n) => [n.id, n]));

  return (
    <svg viewBox="-180 0 460 500" className="w-full h-full">
      <defs>
        <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="4" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      {EDGES.map(([a, b], i) => {
        const na = nodeById[a], nb = nodeById[b];
        const on = activeId === a || activeId === b;
        return (
          <line
            key={i}
            x1={na.x} y1={na.y} x2={nb.x} y2={nb.y}
            stroke={on ? "#10B981" : "rgba(255,255,255,0.12)"}
            strokeWidth={on ? 1.4 : 0.8}
            style={{ transition: "stroke 0.4s, stroke-width 0.4s" }}
          />
        );
      })}
      {PIPELINE.map((n) => {
        const isActive = activeId === n.id;
        const color = n.tier ? tierColor(n.tier) : isActive ? "#10B981" : "#FAFAFA";
        return (
          <g key={n.id} transform={`translate(${n.x}, ${n.y})`}>
            <motion.rect
              x={-52} y={-16} width={104} height={32}
              fill={isActive ? "rgba(16,185,129,0.08)" : "#0a0a0a"}
              stroke={isActive ? "#10B981" : n.tier ? color + "80" : "rgba(255,255,255,0.18)"}
              strokeWidth={isActive ? 1.4 : 1}
              animate={{ scale: isActive ? 1.05 : 1 }}
              transition={{ duration: 0.3 }}
              filter={isActive ? "url(#glow)" : undefined}
            />
            <text
              x={0} y={4}
              textAnchor="middle"
              fontFamily="JetBrains Mono, monospace"
              fontSize="10.5"
              fill={isActive ? "#10B981" : n.tier ? color : "#E5E5E5"}
              style={{ textTransform: "uppercase", letterSpacing: "0.12em" }}
            >
              {n.label}
            </text>
            {n.tier && (
              <circle cx={-42} cy={0} r={2.5} fill={color} />
            )}
          </g>
        );
      })}
    </svg>
  );
}

export default function Hero() {
  const ref = useRef(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end start"] });
  const y = useTransform(scrollYProgress, [0, 1], [0, 120]);
  const opacity = useTransform(scrollYProgress, [0, 0.7], [1, 0.2]);

  return (
    <section
      id="top"
      ref={ref}
      data-testid="hero-section"
      className="relative overflow-hidden landing-hero"
    >
      <div className="absolute inset-0 grid-bg opacity-40 pointer-events-none" />
      <div className="absolute top-0 left-0 right-0 h-px bg-white/10" />

      <div className="relative max-w-[1400px] mx-auto px-4 sm:px-6 md:px-10 w-full landing-hero-frame">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 lg:gap-6 landing-hero-grid">
          <motion.div style={{ y, opacity }} className="lg:col-span-7 xl:col-span-8 relative min-w-0 landing-hero-copy">
            <div className="flex items-baseline gap-3 md:gap-4 landing-hero-mark">
              <span className="font-serif italic text-[1.75rem] md:text-4xl lg:text-[2.5rem] text-neutral-700 leading-none">I.</span>
              <span className="font-mono text-[10px] uppercase tracking-[0.24em] text-neutral-500">
                Hypothesis
              </span>
            </div>

            {/* Mobile flowing headline */}
            <h1 className="font-display font-medium text-white tracking-[-0.03em] lg:hidden landing-hero-title-mobile mt-2">
              <motion.span
                className="block"
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.9, delay: 0.15, ease: [0.19, 1, 0.22, 1] }}
              >
                A document processing pipeline that decides, per chunk, which model
                to use — and measures exactly how much carbon that decision{" "}
                <span className="italic font-serif font-light text-emerald-400">saves.</span>
              </motion.span>
            </h1>

            {/* Desktop — sized so sub + CTAs stay in the same viewport */}
            <h1 className="font-display font-medium text-white tracking-[-0.035em] hidden lg:block landing-hero-title-desktop">
              {HEADLINE_LINES.map((line, i) => (
                <span key={i} className="block overflow-hidden">
                  <motion.span
                    className="block"
                    initial={{ y: "110%" }}
                    animate={{ y: 0 }}
                    transition={{
                      duration: 1.05,
                      delay: 0.15 + i * 0.1,
                      ease: [0.19, 1, 0.22, 1],
                    }}
                  >
                    {line}
                  </motion.span>
                </span>
              ))}
            </h1>

            {/* Locked footer of first viewport: pillars + CTAs */}
            <div className="landing-hero-footer">
              <motion.p
                initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.85, duration: 0.6 }}
                className="text-neutral-400 landing-hero-sub"
              >
                Three pillars —
                <span className="text-white"> adaptive routing</span>,
                <span className="text-white"> carbon-aware scheduling</span>, and
                <span className="text-white"> transparent accounting</span> —
                working chunk by chunk against a live grid signal.
              </motion.p>

              <motion.div
                initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 1.0, duration: 0.6 }}
                className="flex flex-nowrap items-center gap-2 sm:gap-3 md:gap-4 landing-hero-ctas"
              >
                <LiveDemoLink
                  nextPath="/new-job"
                  data-testid="hero-cta-primary"
                  className="group inline-flex shrink-0 items-center justify-center gap-1.5 sm:gap-2 bg-emerald-500 text-black px-3.5 py-2.5 sm:px-5 sm:py-3 font-mono text-[10px] sm:text-[11px] uppercase tracking-[0.14em] sm:tracking-[0.18em] hover:bg-emerald-400 transition-colors emerald-glow"
                >
                  Try Demo
                  <ArrowUpRight className="w-3.5 h-3.5 group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition-transform" strokeWidth={2} />
                </LiveDemoLink>
                <Link
                  href="/login"
                  data-testid="hero-cta-secondary"
                  className="group inline-flex shrink-0 items-center justify-center gap-1.5 sm:gap-2 border border-white/20 text-white px-3.5 py-2.5 sm:px-5 sm:py-3 font-mono text-[10px] sm:text-[11px] uppercase tracking-[0.14em] sm:tracking-[0.18em] hover:border-white/50 transition-colors"
                >
                  Sign In
                  <ArrowRight className="w-3.5 h-3.5 group-hover:translate-x-0.5 transition-transform" strokeWidth={2} />
                </Link>
              </motion.div>
            </div>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.5, duration: 1.2, ease: [0.22, 1, 0.36, 1] }}
            className="lg:col-span-5 xl:col-span-4 relative min-w-0 hidden lg:block landing-hero-diagram"
          >
            <div className="relative border border-white/10 bg-[#080808] landing-hero-diagram-frame">
              {["tl","tr","bl","br"].map((c) => (
                <div key={c} className={`absolute w-3 h-3 border-emerald-400/60
                  ${c==="tl"?"top-2 left-2 border-t border-l":""}
                  ${c==="tr"?"top-2 right-2 border-t border-r":""}
                  ${c==="bl"?"bottom-2 left-2 border-b border-l":""}
                  ${c==="br"?"bottom-2 right-2 border-b border-r":""}
                `} />
              ))}
              <div className="absolute top-3 left-3 flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.2em] text-neutral-500">
                <span className="w-1 h-1 bg-emerald-400 rounded-full" />
                fig. 01 — routing topology
              </div>
              <div className="absolute bottom-3 right-3 font-mono text-[10px] uppercase tracking-[0.2em] text-neutral-600">
                8 nodes / 5 chunks
              </div>
              <NodeGraph />
            </div>
          </motion.div>
        </div>

        {/* Mobile diagram — after CTAs, still in hero but typically below fold on phones */}
        <motion.div
          initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.5, duration: 1.2, ease: [0.22, 1, 0.36, 1] }}
          className="mt-8 lg:hidden relative min-w-0"
        >
          <div className="relative aspect-[4/5] sm:aspect-[3/4] border border-white/10 bg-[#080808]">
            {["tl","tr","bl","br"].map((c) => (
              <div key={c} className={`absolute w-3 h-3 border-emerald-400/60
                ${c==="tl"?"top-2 left-2 border-t border-l":""}
                ${c==="tr"?"top-2 right-2 border-t border-r":""}
                ${c==="bl"?"bottom-2 left-2 border-b border-l":""}
                ${c==="br"?"bottom-2 right-2 border-b border-r":""}
              `} />
            ))}
            <div className="absolute top-3 left-3 flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.2em] text-neutral-500">
              <span className="w-1 h-1 bg-emerald-400 rounded-full" />
              fig. 01 — routing topology
            </div>
            <div className="absolute bottom-3 right-3 font-mono text-[10px] uppercase tracking-[0.2em] text-neutral-600">
              8 nodes / 5 chunks
            </div>
            <NodeGraph />
          </div>
        </motion.div>
      </div>
    </section>
  );
}
