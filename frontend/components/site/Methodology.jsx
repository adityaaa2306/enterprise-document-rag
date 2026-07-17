"use client"

import { motion } from "framer-motion";

const TERMS = [
  { s: "CO₂", label: "grams CO₂-equivalent" },
  { s: "T",   label: "tokens × J/token (compute J)" },
  { s: "PUE", label: "facility overhead (~1.15)" },
  { s: "G",   label: "grid intensity gCO₂/kWh" },
  { s: "kWh", label: "facility J ÷ 3.6e6" },
];

export default function Methodology() {
  return (
    <section id="methodology" data-testid="methodology-section" className="relative py-24 md:py-32 hairline-t">
      <div className="max-w-[1400px] mx-auto px-4 sm:px-6 md:px-10">
        <div className="mb-12">
          <div className="flex items-baseline gap-4 mb-3">
            <span className="font-serif italic text-6xl md:text-7xl text-neutral-800 leading-none">III.</span>
            <span className="font-mono text-[10px] uppercase tracking-[0.24em] text-neutral-500">
              Methodology
            </span>
          </div>
          <h2 className="font-display text-3xl md:text-5xl tracking-tight text-white leading-[1.05] max-w-3xl">
            One equation.<br/>Estimated with <span className="italic font-serif font-light text-emerald-400">documented assumptions.</span>
          </h2>
        </div>

        {/* Equation */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.7 }}
          className="border border-white/10 bg-[#080808] p-5 sm:p-10 md:p-16 overflow-hidden"
        >
          <div className="font-mono text-[10px] uppercase tracking-[0.24em] text-neutral-500 mb-6 md:mb-8">
            eq. 01 — carbon accounting
          </div>
          {/* Mobile: stacked / wrapped so the equation never leaves the box */}
          <div className="font-mono text-[clamp(0.95rem,3.6vw,1.35rem)] sm:text-xl md:text-4xl text-white tracking-tight leading-snug md:leading-tight break-words">
            <span className="text-neutral-500">CO₂e</span>
            <span className="text-neutral-600 mx-1.5 md:mx-2">=</span>
            <span className="text-white">(Σ T·E)</span>
            <span className="text-neutral-600 mx-0.5 md:mx-1">·</span>
            <span style={{ color: "#F59E0B" }}>PUE</span>
            <span className="text-neutral-600 mx-0.5 md:mx-1">→</span>
            <span className="text-white">kWh</span>
            <span className="text-neutral-600 mx-0.5 md:mx-1">·</span>
            <span className="text-emerald-400">G</span>
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
            <div className="font-mono text-[10px] uppercase tracking-[0.24em] text-rose-400/80 mb-4">Baseline · frontier / heavy</div>
            <div className="font-display text-4xl text-white">8.30 <span className="text-lg text-neutral-500">g CO₂e / doc</span></div>
            <p className="mt-4 text-sm text-neutral-400 leading-relaxed">
              Naive conventional path: same token mass, all map + compile charged at heavy / frontier J/token (~6.5 J/tok · Llama 3.3 70B class). No CRE routing.
            </p>
            <div className="mt-6 font-mono text-[11px] text-neutral-500">
              Document Processing · Boundary A · illustrative featured run
            </div>
          </motion.div>
          <motion.div
            initial={{ opacity: 0, y: 20 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }}
            transition={{ duration: 0.6, delay: 0.1 }}
            className="border border-emerald-500/30 bg-[#0a1310] p-8"
          >
            <div className="font-mono text-[10px] uppercase tracking-[0.24em] text-emerald-400 mb-4">Optimized · adaptive route</div>
            <div className="font-display text-4xl text-white">3.97 <span className="text-lg text-neutral-500">g CO₂e / doc</span></div>
            <p className="mt-4 text-sm text-neutral-400 leading-relaxed">
              Per-chunk Light / Medium / Heavy (NIM) with QVA escalation. Same shared stages × PUE × live grid intensity. Interactive RAG is accounted separately in chat.
            </p>
            <div className="mt-6 font-mono text-[11px] text-neutral-500">
              Σ (Tᵢ · Eᵢ) · PUE → kWh · G · illustrative 52% reduction
            </div>
          </motion.div>
        </div>

        <p className="mt-6 font-mono text-[10px] uppercase tracking-[0.18em] text-neutral-500 max-w-3xl leading-relaxed">
          Excluded · model training · hardware manufacturing · end-of-life LCA · Included · PUE facility overhead · live Electricity Maps intensity (single region)
        </p>
      </div>
    </section>
  );
}
