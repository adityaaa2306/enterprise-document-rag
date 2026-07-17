"use client"

import { useState } from "react";
import { motion } from "framer-motion";
import { Switch } from "@/components/ui/switch";

const CHUNKS = [
  { id: 1, name: "Header block",     tokens: 180, complexity: 0.18, label: "table-of-contents" },
  { id: 2, name: "Section 3.1",      tokens: 620, complexity: 0.42, label: "definitional" },
  { id: 3, name: "Clause 4.b",       tokens: 940, complexity: 0.71, label: "cross-reference" },
  { id: 4, name: "Table 7 caption",  tokens: 210, complexity: 0.24, label: "structural" },
  { id: 5, name: "Appendix A",       tokens: 1420, complexity: 0.88, label: "multi-hop reasoning" },
  { id: 6, name: "Signature block",  tokens: 90,  complexity: 0.11, label: "structural" },
];

const tierFor = (c, high) => {
  // when grid is dirty, we bias down (prefer lighter tier)
  if (high) {
    if (c > 0.85) return "heavy";
    if (c > 0.6) return "medium";
    return "light";
  }
  if (c > 0.65) return "heavy";
  if (c > 0.35) return "medium";
  return "light";
};

const tierMeta = {
  light:  { color: "#14B8A6", label: "Light",  model: "Llama 3.2 3B",   jpt: 0.85 },
  medium: { color: "#F59E0B", label: "Medium", model: "Ministral 14B",  jpt: 2.55 },
  heavy:  { color: "#F43F5E", label: "Heavy",  model: "Llama 3.3 70B",  jpt: 6.5 },
};

export default function CarbonRouting() {
  const [highCarbon, setHighCarbon] = useState(false);
  const grid = highCarbon ? 620 : 210;

  const totalCO2 = CHUNKS.reduce((acc, c) => {
    const t = tierMeta[tierFor(c.complexity, highCarbon)];
    return acc + (c.tokens * t.jpt * grid) / 1e6;
  }, 0);

  const baseline = CHUNKS.reduce(
    (acc, c) => acc + (c.tokens * tierMeta.heavy.jpt * grid) / 1e6,
    0
  );

  const savings = ((1 - totalCO2 / baseline) * 100).toFixed(1);

  return (
    <section id="routing" data-testid="carbon-routing" className="relative py-24 md:py-32 hairline-t bg-[#070707]">
      <div className="max-w-[1400px] mx-auto px-6 md:px-10">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-10 mb-14">
          <div className="lg:col-span-7">
            <div className="font-mono text-[10px] uppercase tracking-[0.24em] text-neutral-500 mb-2">
              05 · Carbon-aware routing
            </div>
            <h2 className="font-display text-3xl md:text-5xl tracking-tight text-white leading-[1.05]">
              The same document,<br/>
              routed <span className="italic font-serif font-light text-emerald-400">differently</span> by the grid.
            </h2>
          </div>
          <div className="lg:col-span-5 flex items-end">
            <p className="text-neutral-400 leading-relaxed text-[15px]">
              Illustrative demo: toggle grid intensity and watch expected CO₂e change as Light /
              Medium / Heavy (Llama 3.2 3B · Ministral 14B · Llama 3.3 70B) assignments shift.
              Live routing still respects CRE capability floors before carbon weights.
            </p>
          </div>
        </div>

        {/* Toggle */}
        <div className="border border-white/10 bg-[#080808]">
          <div className="hairline-b px-6 py-5 flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-4">
              <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-neutral-500">Grid signal</span>
              <div className="flex items-center gap-3">
                <span className={`font-mono text-[12px] tracking-tight transition-colors ${!highCarbon ? "text-emerald-400" : "text-neutral-600"}`}>
                  low · 210 gCO₂/kWh
                </span>
                <Switch
                  data-testid="grid-toggle"
                  checked={highCarbon}
                  onCheckedChange={setHighCarbon}
                  className="data-[state=checked]:bg-rose-500 data-[state=unchecked]:bg-emerald-500"
                />
                <span className={`font-mono text-[12px] tracking-tight transition-colors ${highCarbon ? "text-rose-400" : "text-neutral-600"}`}>
                  high · 620 gCO₂/kWh
                </span>
              </div>
            </div>
            <div className="flex items-center gap-6 font-mono text-[11px]">
              <div>
                <span className="text-neutral-500 uppercase tracking-[0.16em] mr-2">Total</span>
                <motion.span key={totalCO2} initial={{ opacity: 0.4 }} animate={{ opacity: 1 }} className="text-white">
                  {totalCO2.toFixed(2)} g CO₂
                </motion.span>
              </div>
              <div>
                <span className="text-neutral-500 uppercase tracking-[0.16em] mr-2">Savings</span>
                <motion.span key={savings} initial={{ opacity: 0.4 }} animate={{ opacity: 1 }} className="text-emerald-400">
                  {savings}%
                </motion.span>
              </div>
            </div>
          </div>

          {/* Chunk grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-px bg-white/5">
            {CHUNKS.map((c, i) => {
              const tier = tierFor(c.complexity, highCarbon);
              const meta = tierMeta[tier];
              const co2 = ((c.tokens * meta.jpt * grid) / 1e6).toFixed(3);
              return (
                <motion.div
                  key={c.id}
                  layout
                  initial={{ opacity: 0, y: 12 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true }}
                  transition={{ delay: i * 0.04, duration: 0.5 }}
                  className="relative bg-[#080808] p-6 group"
                >
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-neutral-500">
                        chunk_{String(c.id).padStart(2, "0")}
                      </div>
                      <div className="font-display text-lg text-white mt-1">{c.name}</div>
                      <div className="font-mono text-[11px] text-neutral-500 mt-0.5">{c.label}</div>
                    </div>
                    <motion.div
                      key={tier}
                      initial={{ scale: 0.85, opacity: 0 }}
                      animate={{ scale: 1, opacity: 1 }}
                      transition={{ duration: 0.35 }}
                      className="flex items-center gap-2"
                    >
                      <span className="w-2 h-2" style={{ background: meta.color }} />
                      <span className="font-mono text-[10px] uppercase tracking-[0.14em]" style={{ color: meta.color }}>
                        {meta.label}
                      </span>
                    </motion.div>
                  </div>

                  <div className="mt-6">
                    <div className="h-1 w-full bg-white/5 relative overflow-hidden">
                      <motion.div
                        key={tier + c.id}
                        initial={{ width: 0 }}
                        animate={{ width: `${c.complexity * 100}%` }}
                        transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
                        className="h-full"
                        style={{ background: meta.color }}
                      />
                    </div>
                    <div className="flex items-center justify-between mt-2 font-mono text-[10px] text-neutral-500 tracking-tight">
                      <span>{c.tokens} tok</span>
                      <span>complexity {c.complexity.toFixed(2)}</span>
                      <motion.span
                        key={co2}
                        initial={{ opacity: 0.4 }}
                        animate={{ opacity: 1 }}
                        className="text-white"
                      >
                        {co2} g
                      </motion.span>
                    </div>
                  </div>
                </motion.div>
              );
            })}
          </div>

          {/* Footer */}
          <div className="hairline-t px-6 py-4 flex flex-wrap items-center justify-between gap-4 font-mono text-[10px] uppercase tracking-[0.18em] text-neutral-500">
            <div className="flex items-center gap-5">
              {["light", "medium", "heavy"].map((t) => (
                <span key={t} className="flex items-center gap-2">
                  <span className="w-2 h-2" style={{ background: tierMeta[t].color }} />
                  {tierMeta[t].label} · {tierMeta[t].model}
                </span>
              ))}
            </div>
            <div>baseline (heavy-only) → {baseline.toFixed(2)} g CO₂</div>
          </div>
        </div>
      </div>
    </section>
  );
}
