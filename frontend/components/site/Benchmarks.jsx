"use client"

import { motion } from "framer-motion";

const METRICS = [
  { value: "20%", label: "carbon reduction · at scale", note: "52.1% featured run" },
  { value: "15%", label: "energy reduction" },
  { value: "25%", label: "faster processing" },
  { value: "60%", label: "cost reduction" },
  { value: "60%", label: "less large-model usage" },
];

// gCO₂ per document
const COMPARISON = [
  { name: "GPT-o3",           value: 14.2, ours: false },
  { name: "GPT-4",            value: 11.6, ours: false },
  { name: "Claude 4 Opus",    value: 10.4, ours: false },
  { name: "Gemini 2.5 Pro",   value: 8.9,  ours: false },
  { name: "Green / Agentic",  value: 3.97, ours: true },
];

const max = Math.max(...COMPARISON.map((c) => c.value));

export default function Benchmarks() {
  return (
    <section id="benchmarks" data-testid="benchmarks-section" className="relative py-24 md:py-32 hairline-t bg-[#070707]">
      <div className="max-w-[1400px] mx-auto px-6 md:px-10">
        <div className="mb-14">
          <div className="font-mono text-[10px] uppercase tracking-[0.24em] text-neutral-500 mb-2">
            10 · Benchmarks
          </div>
          <h2 className="font-display text-3xl md:text-5xl tracking-tight text-white leading-[1.05] max-w-3xl">
            The numbers, <span className="italic font-serif font-light text-emerald-400">unrounded.</span>
          </h2>
        </div>

        {/* metric grid */}
        <div className="grid grid-cols-2 md:grid-cols-5 divide-x divide-y md:divide-y-0 divide-white/10 border border-white/10">
          {METRICS.map((m, i) => (
            <motion.div
              key={m.label}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: i * 0.08, duration: 0.6 }}
              className="p-6 md:p-8"
            >
              <div className="font-display text-4xl md:text-5xl text-white tracking-tighter">{m.value}</div>
              <div className="mt-3 font-mono text-[10px] uppercase tracking-[0.16em] text-neutral-500 leading-relaxed">
                {m.label}
              </div>
              {m.note && (
                <div className="mt-2 font-mono text-[10px] tracking-tight text-emerald-400/90">
                  {m.note}
                </div>
              )}
            </motion.div>
          ))}
        </div>

        {/* bar chart */}
        <div className="mt-4 border border-white/10 bg-[#080808]">
          <div className="hairline-b px-6 py-4 flex items-center justify-between font-mono text-[10px] uppercase tracking-[0.2em]">
            <span className="text-neutral-400">Chart 01 · CO₂ per document (g)</span>
            <span className="text-neutral-600">lower is better</span>
          </div>
          <div className="p-6 md:p-8">
            {COMPARISON.map((c, i) => (
              <motion.div
                key={c.name}
                initial={{ opacity: 0, x: -20 }}
                whileInView={{ opacity: 1, x: 0 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.09, duration: 0.6 }}
                className={`grid grid-cols-12 items-center py-5 ${i < COMPARISON.length - 1 ? "hairline-b" : ""}`}
              >
                <div className="col-span-4 md:col-span-3 flex items-center gap-3">
                  {c.ours && <span className="w-1.5 h-1.5 bg-emerald-400 rounded-full" />}
                  <span className={`font-mono text-[12px] uppercase tracking-[0.14em] ${c.ours ? "text-emerald-400" : "text-neutral-300"}`}>
                    {c.name}
                  </span>
                </div>
                <div className="col-span-6 md:col-span-7">
                  <div className="h-2 bg-white/5 relative">
                    <motion.div
                      initial={{ width: 0 }}
                      whileInView={{ width: `${(c.value / max) * 100}%` }}
                      viewport={{ once: true }}
                      transition={{ delay: 0.2 + i * 0.1, duration: 1, ease: [0.22, 1, 0.36, 1] }}
                      className="h-full"
                      style={{ background: c.ours ? "#10B981" : "#3F3F46" }}
                    />
                  </div>
                </div>
                <div className="col-span-2 text-right font-mono text-[13px] text-white">
                  {c.value.toFixed(2)} g
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
