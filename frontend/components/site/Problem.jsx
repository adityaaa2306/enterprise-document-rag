"use client"

import { motion } from "framer-motion";

const TIERS = [
  { tier: "light", model: "DistilBART", jpt: 0.85, co2: 0.34, color: "#14B8A6" },
  { tier: "medium", model: "Gemma 2B", jpt: 2.55, co2: 1.02, color: "#F59E0B" },
  { tier: "heavy", model: "Llama 3.1 8B", jpt: 6.5, co2: 2.6, color: "#F43F5E" },
];

export default function Problem() {
  return (
    <section id="problem" data-testid="problem-section" className="relative py-24 md:py-32">
      <div className="max-w-[1400px] mx-auto px-6 md:px-10">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-12">
          {/* Left column */}
          <div className="lg:col-span-5">
            <div className="flex items-baseline gap-4 mb-8">
              <span className="font-serif italic text-6xl md:text-7xl text-neutral-800 leading-none">II.</span>
              <span className="font-mono text-[10px] uppercase tracking-[0.24em] text-neutral-500">
                The problem
              </span>
            </div>
            <h2 className="font-display text-3xl md:text-5xl tracking-tight text-white leading-[1.05]">
              Every chunk hits the biggest model.<br/>
              <span className="text-neutral-500">Every</span> <span className="italic font-serif text-emerald-400 font-light">watt.</span> <span className="text-neutral-500">Every</span> <span className="italic font-serif text-emerald-400 font-light">gram.</span>
            </h2>
            <p className="mt-8 text-neutral-400 max-w-md leading-relaxed">
              Traditional pipelines route a table-of-contents lookup through the same 70B-parameter
              transformer that summarises a legal contract. The math doesn't survive scale.
            </p>

            <div className="mt-12 grid grid-cols-2 gap-6">
              <div className="hairline-t pt-4">
                <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-neutral-500">Baseline</div>
                <div className="font-display text-3xl mt-1 text-white">~8.3<span className="text-base text-neutral-500 ml-1">g</span></div>
                <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-neutral-600 mt-1">CO₂ / doc</div>
              </div>
              <div className="hairline-t pt-4">
                <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-neutral-500">At scale</div>
                <div className="font-display text-3xl mt-1 text-white">~100<span className="text-base text-neutral-500 ml-1">g</span></div>
                <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-neutral-600 mt-1">CO₂ / 1k docs</div>
              </div>
            </div>
          </div>

          {/* Right column: table */}
          <div className="lg:col-span-7">
            <div className="border border-white/10 bg-[#080808]">
              <div className="hairline-b px-6 py-4 flex items-center justify-between">
                <div className="font-mono text-[10px] uppercase tracking-[0.2em] text-neutral-400">
                  Table 01 — Energy cost by tier
                </div>
                <div className="font-mono text-[10px] uppercase tracking-[0.2em] text-neutral-600">J / token</div>
              </div>
              <div className="grid grid-cols-12 px-6 py-3 hairline-b font-mono text-[10px] uppercase tracking-[0.18em] text-neutral-500">
                <div className="col-span-3">Tier</div>
                <div className="col-span-4">Model</div>
                <div className="col-span-2 text-right">J/tok</div>
                <div className="col-span-3 text-right">CO₂/1k tok</div>
              </div>
              {TIERS.map((t, i) => (
                <motion.div
                  key={t.tier}
                  initial={{ opacity: 0, y: 10 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true }}
                  transition={{ delay: i * 0.1, duration: 0.6 }}
                  className="grid grid-cols-12 items-center px-6 py-5 hairline-b group hover:bg-white/[0.02] transition-colors"
                >
                  <div className="col-span-3 flex items-center gap-2.5">
                    <span className="w-2 h-2" style={{ background: t.color }} />
                    <span className="font-mono text-[13px] uppercase tracking-[0.14em] text-white">{t.tier}</span>
                  </div>
                  <div className="col-span-4 font-mono text-[13px] text-neutral-300">{t.model}</div>
                  <div className="col-span-2 font-mono text-[13px] text-right text-white">{t.jpt.toFixed(2)}</div>
                  <div className="col-span-3 font-mono text-[13px] text-right text-neutral-400">{t.co2.toFixed(2)} g</div>
                </motion.div>
              ))}
              {/* Equation */}
              <div className="px-6 py-6 bg-[#0a0a0a]">
                <div className="font-mono text-[10px] uppercase tracking-[0.2em] text-neutral-500 mb-3">
                  Baseline derivation
                </div>
                <div className="font-mono text-sm text-neutral-300 leading-relaxed">
                  <span className="text-neutral-500">CO₂ =</span> tokens
                  <span className="text-neutral-600"> · </span>
                  <span className="text-amber-400">J/tok</span>
                  <span className="text-neutral-600"> · </span>
                  <span className="text-emerald-400">grid_intensity</span>
                  <span className="text-neutral-600"> · </span>
                  <span className="text-neutral-500">10⁻⁶</span>
                </div>
                <div className="font-mono text-[11px] text-neutral-500 mt-2">
                  {" = 3,250 · 6.5 · 480 · 10⁻⁶ ≈ 10.1 g / heavy-only run"}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
