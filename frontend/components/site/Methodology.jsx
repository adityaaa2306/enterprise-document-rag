"use client"

import { motion } from "framer-motion";

const TERMS = [
  { s: "CO₂", label: "grams CO₂-equivalent" },
  { s: "T",   label: "total tokens processed" },
  { s: "E",   label: "J/token for chosen tier" },
  { s: "G",   label: "grid intensity gCO₂/kWh" },
  { s: "1e−6", label: "scale factor J → kWh · g" },
];

export default function Methodology() {
  return (
    <section id="methodology" data-testid="methodology-section" className="relative py-24 md:py-32 hairline-t">
      <div className="max-w-[1400px] mx-auto px-6 md:px-10">
        <div className="mb-12">
          <div className="flex items-baseline gap-4 mb-3">
            <span className="font-serif italic text-6xl md:text-7xl text-neutral-800 leading-none">III.</span>
            <span className="font-mono text-[10px] uppercase tracking-[0.24em] text-neutral-500">
              Methodology
            </span>
          </div>
          <h2 className="font-display text-3xl md:text-5xl tracking-tight text-white leading-[1.05] max-w-3xl">
            One equation.<br/>Measured, not <span className="italic font-serif font-light text-emerald-400">estimated.</span>
          </h2>
        </div>

        {/* Equation */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.7 }}
          className="border border-white/10 bg-[#080808] p-10 md:p-16"
        >
          <div className="font-mono text-[10px] uppercase tracking-[0.24em] text-neutral-500 mb-8">
            eq. 01 — carbon accounting
          </div>
          <div className="font-mono text-3xl md:text-5xl text-white tracking-tight leading-tight">
            <span className="text-neutral-500">CO₂</span>
            <span className="text-neutral-600 mx-2">=</span>
            <span className="text-white">Σ<sub className="text-lg text-neutral-500">chunks</sub></span>
            <span className="text-neutral-600 mx-1">(</span>
            <span className="text-white">T</span>
            <span className="text-neutral-600 mx-1">·</span>
            <span style={{ color: "#F59E0B" }}>E</span>
            <span className="text-neutral-600 mx-1">·</span>
            <span className="text-emerald-400">G</span>
            <span className="text-neutral-600 mx-1">·</span>
            <span className="text-neutral-500">10⁻⁶</span>
            <span className="text-neutral-600 mx-1">)</span>
          </div>
          <div className="mt-10 grid grid-cols-2 md:grid-cols-5 gap-6">
            {TERMS.map((t) => (
              <div key={t.s} className="hairline-t pt-3">
                <div className="font-mono text-lg text-white">{t.s}</div>
                <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-neutral-500 mt-1">
                  {t.label}
                </div>
              </div>
            ))}
          </div>
        </motion.div>

        {/* Baseline vs Optimized */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
          <motion.div
            initial={{ opacity: 0, y: 20 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }}
            transition={{ duration: 0.6 }}
            className="border border-white/10 bg-[#080808] p-8"
          >
            <div className="font-mono text-[10px] uppercase tracking-[0.24em] text-rose-400/80 mb-4">Baseline · heavy only</div>
            <div className="font-display text-4xl text-white">8.30 <span className="text-lg text-neutral-500">g CO₂ / doc</span></div>
            <p className="mt-4 text-sm text-neutral-400 leading-relaxed">
              Every chunk routes to Llama 3.1 8B regardless of complexity. E = 6.5 J/token, uniform.
            </p>
            <div className="mt-6 font-mono text-[11px] text-neutral-500">
              T=3,250 · E=6.5 · G=480 · 10⁻⁶
            </div>
          </motion.div>
          <motion.div
            initial={{ opacity: 0, y: 20 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }}
            transition={{ duration: 0.6, delay: 0.1 }}
            className="border border-emerald-500/30 bg-[#0a1310] p-8"
          >
            <div className="font-mono text-[10px] uppercase tracking-[0.24em] text-emerald-400 mb-4">Optimized · adaptive route</div>
            <div className="font-display text-4xl text-white">3.97 <span className="text-lg text-neutral-500">g CO₂ / doc</span></div>
            <p className="mt-4 text-sm text-neutral-400 leading-relaxed">
              Per-chunk tier selection with grid-aware weighting. 52.1% reduction on the featured run.
            </p>
            <div className="mt-6 font-mono text-[11px] text-neutral-500">
              Σ (Tᵢ · Eᵢ · G · 10⁻⁶) · G = 210–480
            </div>
          </motion.div>
        </div>

        <p className="mt-6 font-mono text-[10px] uppercase tracking-[0.18em] text-neutral-500 max-w-3xl leading-relaxed">
          Excluded from calculation · model training emissions · hardware manufacturing · end-of-life LCA · datacenter PUE overhead.
        </p>
      </div>
    </section>
  );
}
