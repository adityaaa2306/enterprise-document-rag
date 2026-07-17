"use client"

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";

const ITEMS = [
  {
    q: "Why not always use the biggest model?",
    a: "A 70B-class model summarising a signature block does the same job as a 3B-class model at many times the energy cost. The Capability Requirement Engine and per-chunk router assign Light / Medium / Heavy (Llama 3.2 3B · Ministral 14B · Llama 3.3 70B) only as needed — with QVA escalation when quality fails.",
  },
  {
    q: "Is region scheduling actually live?",
    a: "Live intensity comes from Electricity Maps for the configured execution region (default: India). Multi-region carbon-optimal placement is architecture-ready but not active — the product does not fake global hop routing. Accounting always uses the Region Scheduler’s intensity for that single region.",
  },
  {
    q: "What's excluded from the carbon calculation?",
    a: "Model training, hardware manufacturing (embodied carbon), and end-of-life LCA. Operational Boundary A does include facility electricity via PUE: tokens × J/token × PUE × grid intensity. Document Processing and Interactive RAG are reported separately.",
  },
  {
    q: "How is complexity scored?",
    a: "Document-level CRE sets capability floors; per-chunk feature extraction (complexity, importance, and related signals) feeds the adaptive router. Eco / Balanced / Performance only reweight utility — they never drop below floors or skip summarisation.",
  },
  {
    q: "What happens on validation failure?",
    a: "The Quality Validation Agent (QVA) can escalate a chunk one tier (bounded). If the escalated tier also fails, the chunk is flagged; the router does not silently loop forever.",
  },
  {
    q: "Are the model tiers configurable?",
    a: "Yes. LIGHT_MODEL_PRIMARY / MEDIUM_MODEL_PRIMARY / HEAVY_MODEL_PRIMARY (plus fallbacks) map the canonical Light / Medium / Heavy roles to NVIDIA NIM models and the shared J/token table. Swapping a primary is an environment change — not a rewrite of the accounting equation.",
  },
];

export default function FAQ() {
  return (
    <section id="faq" data-testid="faq-section" className="relative py-24 md:py-32 hairline-t">
      <div className="max-w-[1400px] mx-auto px-6 md:px-10">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-10">
          <div className="lg:col-span-4">
            <div className="font-mono text-[10px] uppercase tracking-[0.24em] text-neutral-500 mb-2">
              13 · FAQ
            </div>
            <h2 className="font-display text-3xl md:text-5xl tracking-tight text-white leading-[1.05]">
              Anticipated <span className="italic font-serif font-light text-emerald-400">objections.</span>
            </h2>
            <p className="mt-6 text-neutral-500 text-sm leading-relaxed max-w-sm">
              Six questions we expect from engineers reviewing this in detail.
            </p>
          </div>
          <div className="lg:col-span-8 border-t border-white/10">
            <Accordion type="single" collapsible className="w-full" data-testid="faq-accordion">
              {ITEMS.map((it, i) => (
                <AccordionItem key={i} value={`item-${i}`} className="border-b border-white/10 !border-t-0">
                  <AccordionTrigger
                    data-testid={`faq-trigger-${i}`}
                    className="hover:no-underline py-6 group"
                  >
                    <div className="flex items-baseline gap-5 text-left">
                      <span className="font-mono text-[11px] text-neutral-600 tracking-[0.14em]">
                        {String(i + 1).padStart(2, "0")}
                      </span>
                      <span className="font-display text-lg md:text-xl text-white tracking-tight group-hover:text-emerald-400 transition-colors">
                        {it.q}
                      </span>
                    </div>
                  </AccordionTrigger>
                  <AccordionContent className="pb-6 pl-[52px] text-neutral-400 leading-relaxed text-[15px]">
                    {it.a}
                  </AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
          </div>
        </div>
      </div>
    </section>
  );
}
