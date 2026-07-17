"use client"

import { motion } from "framer-motion";
import { X, Check, ArrowRight } from "lucide-react";

const STEPS = [
  {
    n: "01",
    label: "Assigned",
    tier: "light",
    color: "#14B8A6",
    model: "Llama 3.2 3B",
    status: "attempt",
    icon: null,
    body: "Chunk routed to light tier after CRE + feature scoring (complexity 0.31).",
  },
  {
    n: "02",
    label: "Failed validation",
    tier: "light",
    color: "#F43F5E",
    model: "QVA reject",
    status: "reject",
    icon: X,
    body: "Quality Validation Agent fails lexical / semantic checks. Bounded escalation triggers.",
  },
  {
    n: "03",
    label: "Escalated · passed",
    tier: "medium",
    color: "#10B981",
    model: "Ministral 14B",
    status: "accept",
    icon: Check,
    body: "Re-routed to medium tier. QVA passes — tokens attributed at medium J/token for Document Processing CO₂e.",
  },
];

export default function Validation() {
  return (
    <section id="validation" data-testid="validation-section" className="relative py-24 md:py-32 hairline-t bg-[#070707]">
      <div className="max-w-[1400px] mx-auto px-6 md:px-10">
        <div className="mb-12">
          <div className="font-mono text-[10px] uppercase tracking-[0.24em] text-neutral-500 mb-2">
            07 · Validation
          </div>
          <h2 className="font-display text-3xl md:text-5xl tracking-tight text-white leading-[1.05]">
            Escalate only when <span className="italic font-serif font-light text-emerald-400">needed.</span>
          </h2>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 md:gap-0 md:divide-x md:divide-white/10 border border-white/10 bg-[#080808]">
          {STEPS.map((s, i) => {
            const Icon = s.icon;
            return (
              <motion.div
                key={s.n}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.15, duration: 0.6 }}
                className="relative p-8 md:p-10"
              >
                {i < STEPS.length - 1 && (
                  <ArrowRight className="hidden md:block absolute -right-3 top-1/2 -translate-y-1/2 w-5 h-5 text-neutral-600 bg-[#080808] z-10" strokeWidth={1.2} />
                )}
                <div className="flex items-center justify-between mb-8">
                  <span className="font-serif italic text-4xl text-neutral-800">{s.n}</span>
                  {Icon && (
                    <div className="w-8 h-8 border flex items-center justify-center" style={{ borderColor: s.color, background: s.color + "15" }}>
                      <Icon className="w-4 h-4" style={{ color: s.color }} strokeWidth={2} />
                    </div>
                  )}
                </div>
                <div className="font-mono text-[10px] uppercase tracking-[0.18em] mb-2" style={{ color: s.color }}>
                  {s.label}
                </div>
                <div className="font-display text-xl text-white tracking-tight">{s.model}</div>
                <p className="mt-3 text-sm text-neutral-400 leading-relaxed">{s.body}</p>
                <div className="mt-8 h-1 w-full bg-white/5">
                  <motion.div
                    initial={{ width: 0 }}
                    whileInView={{ width: `${(i + 1) * 33.3}%` }}
                    viewport={{ once: true }}
                    transition={{ delay: 0.4 + i * 0.15, duration: 0.8 }}
                    className="h-full"
                    style={{ background: s.color }}
                  />
                </div>
              </motion.div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
