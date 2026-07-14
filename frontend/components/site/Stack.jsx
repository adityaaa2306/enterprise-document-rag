"use client"

import { motion } from "framer-motion";

const ROWS = [
  { area: "Frontend",   items: "Next.js · Tailwind · Radix UI · shadcn/ui" },
  { area: "Backend",    items: "FastAPI · LangGraph · SQLite · ChromaDB" },
  { area: "Models",     items: "DistilBART · Gemma 2B · Llama 3.1 8B · MiniLM-L6-v2" },
  { area: "Carbon data", items: "Electricity Maps API · region-resolved intensity" },
  { area: "Infra",      items: "Docker · uvicorn · pluggable region scheduler" },
];

export default function Stack() {
  return (
    <section id="stack" data-testid="stack-section" className="relative py-24 md:py-32 hairline-t">
      <div className="max-w-[1400px] mx-auto px-6 md:px-10">
        <div className="mb-10">
          <div className="font-mono text-[10px] uppercase tracking-[0.24em] text-neutral-500 mb-2">
            11 · Stack
          </div>
          <h2 className="font-display text-3xl md:text-5xl tracking-tight text-white">
            What runs it.
          </h2>
        </div>

        <div className="border border-white/10 bg-[#080808]">
          <div className="grid grid-cols-12 px-6 py-3 hairline-b font-mono text-[10px] uppercase tracking-[0.18em] text-neutral-500">
            <div className="col-span-4">Layer</div>
            <div className="col-span-8">Components</div>
          </div>
          {ROWS.map((r, i) => (
            <motion.div
              key={r.area}
              initial={{ opacity: 0 }}
              whileInView={{ opacity: 1 }}
              viewport={{ once: true }}
              transition={{ delay: i * 0.06, duration: 0.5 }}
              className="grid grid-cols-12 px-6 py-5 hairline-b last:border-b-0 group hover:bg-white/[0.02] transition-colors"
            >
              <div className="col-span-4 font-mono text-[12px] uppercase tracking-[0.14em] text-white">
                {r.area}
              </div>
              <div className="col-span-8 font-mono text-[13px] text-neutral-400 group-hover:text-neutral-200 transition-colors">
                {r.items}
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
