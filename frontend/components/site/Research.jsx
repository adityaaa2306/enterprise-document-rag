"use client"

import { motion } from "framer-motion";

const CARDS = [
  {
    tag: "What's novel",
    body: "Per-chunk routing decisions are conditioned on live grid intensity — not just chunk complexity. The optimizer targets carbon, not latency alone.",
  },
  {
    tag: "Simulated vs live",
    body: "Model inference and validation are live. Region scheduling is simulated against Electricity Maps data. Fine-tuning of the router is offline.",
  },
  {
    tag: "Known limitations",
    body: "No training-time accounting. Grid signal lags by ~5 minutes. Escalation is bounded to one step. Multi-tenant queue effects are out of scope.",
  },
];

export default function Research() {
  return (
    <section id="research" data-testid="research-section" className="relative py-24 md:py-32 hairline-t bg-[#070707]">
      <div className="max-w-[1400px] mx-auto px-6 md:px-10">
        <div className="mb-12">
          <div className="flex items-baseline gap-4 mb-3">
            <span className="font-serif italic text-6xl md:text-7xl text-neutral-800 leading-none">IV.</span>
            <span className="font-mono text-[10px] uppercase tracking-[0.24em] text-neutral-500">
              Research &amp; honest disclosure
            </span>
          </div>
          <h2 className="font-display text-3xl md:text-5xl tracking-tight text-white leading-[1.05]">
            What's <span className="italic font-serif font-light text-emerald-400">real,</span> what isn't.
          </h2>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {CARDS.map((c, i) => (
            <motion.div
              key={c.tag}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: i * 0.1, duration: 0.6 }}
              className="border border-white/10 bg-[#080808] p-8 hover:border-white/20 transition-colors"
            >
              <div className="flex items-center justify-between mb-6">
                <div className="font-mono text-[10px] uppercase tracking-[0.2em] text-emerald-400">{c.tag}</div>
                <span className="font-serif italic text-2xl text-neutral-700">
                  {String(i + 1).padStart(2, "0")}
                </span>
              </div>
              <p className="text-[15px] text-neutral-400 leading-relaxed">{c.body}</p>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
