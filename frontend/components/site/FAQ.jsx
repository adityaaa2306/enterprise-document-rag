"use client"

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";

const ITEMS = [
  {
    q: "Why not always use the biggest model?",
    a: "A 70B-parameter transformer summarising a signature block does the same job as a 1B-parameter model at ~30× the energy cost. Routing by chunk complexity avoids paying that cost when the task doesn't demand it.",
  },
  {
    q: "Is region scheduling actually live?",
    a: "No. The candidate-region ranking is derived from live Electricity Maps data, but execution runs in a single region (us-west-2). The scheduler interface is production-ready, the deployment isn't.",
  },
  {
    q: "What's excluded from the carbon calculation?",
    a: "Model training emissions, hardware manufacturing (embodied carbon), end-of-life LCA, and datacenter PUE overhead. The equation covers only inference-time energy × grid intensity.",
  },
  {
    q: "How is complexity scored?",
    a: "A zero-shot classifier assigns a 0–1 complexity score per chunk using entity density, syntactic depth, cross-reference count, and mean sentence length. Signals are combined via a small learned linear head.",
  },
  {
    q: "What happens on validation failure?",
    a: "One bounded escalation to the next tier. If the escalated tier also fails, the output is flagged for review; the router does not silently loop.",
  },
  {
    q: "Are the model tiers configurable?",
    a: "Yes. The tier registry maps a canonical role (light / medium / heavy) to a concrete model plus its measured J/token. Swapping DistilBART for TinyLlama is a one-line config change.",
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
