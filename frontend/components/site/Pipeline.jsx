"use client"

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Plus, Minus } from "lucide-react";

const STAGES = [
  { id: "parse", label: "Parse",              latency: "12 ms",  detail: "PDF / DOCX / plaintext extraction. Structural map returned as JSON — headers, tables, footnotes preserved for downstream capability analysis." },
  { id: "capability", label: "Capability",   latency: "8 ms",   detail: "Zero-shot classifier assigns a complexity score (0–1) to each region. Signals: entity density, syntactic depth, cross-reference count, mean sentence length." },
  { id: "chunk", label: "Chunking",          latency: "6 ms",   detail: "Semantic chunker with 512-token target, adaptive to detected sections. Overlap of 40 tokens preserves contextual continuity across boundaries." },
  { id: "route", label: "Carbon route",      latency: "24 ms",  detail: "Route(chunk) → tier ∈ {light, medium, heavy} given complexity, current grid_intensity, and per-tier J/token. Ties broken by lowest expected CO₂." },
  { id: "infer_l", label: "Light infer",     latency: "310 ms", detail: "DistilBART. 0.85 J/token. Handles boilerplate, extraction, TOC-like structures. Fastest tier — carbon-friendly default." },
  { id: "infer_m", label: "Medium infer",    latency: "820 ms", detail: "Gemma 2B. 2.55 J/token. Handles moderate reasoning, summarisation, contained multi-hop." },
  { id: "infer_h", label: "Heavy infer",     latency: "2.1 s",  detail: "Llama 3.1 8B. 6.5 J/token. Reserved for cross-document synthesis, long-form generation, and validation escalations." },
  { id: "validate", label: "Validate",       latency: "34 ms",  detail: "Confidence scoring against a MiniLM embedding of the expected schema. Below-threshold outputs escalate one tier." },
  { id: "escalate", label: "Escalation",     latency: "±1 tier", detail: "Bounded escalation: light → medium → heavy. Max one escalation per chunk. Cost is logged for the accounting layer." },
  { id: "compile", label: "Compile",         latency: "18 ms",  detail: "Chunk outputs are reassembled in source order. Metadata (tier chosen, tokens, latency, CO₂) attached per chunk." },
  { id: "carbon", label: "Carbon accounting", latency: "—",     detail: "Per-run ledger: baseline vs optimized CO₂, tokens by tier, region, and grid intensity at execution time." },
];

export default function Pipeline() {
  const [open, setOpen] = useState(3);

  return (
    <section id="pipeline" data-testid="pipeline-section" className="relative py-24 md:py-32 hairline-t">
      <div className="max-w-[1400px] mx-auto px-6 md:px-10">
        <div className="flex items-baseline justify-between mb-12">
          <div>
            <div className="font-mono text-[10px] uppercase tracking-[0.24em] text-neutral-500 mb-2">
              04 · Pipeline
            </div>
            <h2 className="font-display text-3xl md:text-5xl tracking-tight text-white">
              Eleven stages,<br/>
              <span className="italic font-serif font-light text-emerald-400">each accountable.</span>
            </h2>
          </div>
          <div className="hidden md:block font-mono text-[10px] uppercase tracking-[0.2em] text-neutral-600">
            expand any row for detail
          </div>
        </div>

        <div className="border border-white/10 bg-[#080808]">
          {STAGES.map((s, i) => {
            const isOpen = open === i;
            return (
              <div key={s.id} className={`${i !== 0 ? "hairline-t" : ""}`}>
                <button
                  data-testid={`pipeline-stage-${s.id}`}
                  onClick={() => setOpen(isOpen ? -1 : i)}
                  className="w-full grid grid-cols-12 items-center px-6 py-5 text-left group hover:bg-white/[0.02] transition-colors"
                >
                  <div className="col-span-1 font-mono text-[11px] text-neutral-600">
                    {String(i + 1).padStart(2, "0")}
                  </div>
                  <div className="col-span-6 md:col-span-5 font-display text-lg md:text-xl text-white tracking-tight">
                    {s.label}
                  </div>
                  <div className="col-span-4 md:col-span-5 font-mono text-[11px] uppercase tracking-[0.18em] text-neutral-500">
                    <span className="text-neutral-600 mr-2">latency</span>{s.latency}
                  </div>
                  <div className="col-span-1 flex justify-end">
                    {isOpen ? <Minus className="w-4 h-4 text-emerald-400" /> : <Plus className="w-4 h-4 text-neutral-500 group-hover:text-white transition-colors" />}
                  </div>
                </button>
                <AnimatePresence initial={false}>
                  {isOpen && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
                      className="overflow-hidden"
                    >
                      <div className="grid grid-cols-12 gap-6 px-6 pb-7 pt-1">
                        <div className="col-span-1" />
                        <div className="col-span-11 md:col-span-8 text-neutral-400 leading-relaxed text-[15px]">
                          {s.detail}
                        </div>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
