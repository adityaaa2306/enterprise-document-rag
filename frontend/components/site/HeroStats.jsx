"use client"

import { motion } from "framer-motion";

const STATS = [
  ["52.1%", "carbon reduction / last run"],
  ["8.3 g", "CO₂ baseline / doc"],
  ["24 ms", "avg routing latency"],
];

/** Below-fold signal strip — kept out of the hero first viewport. */
export default function HeroStats() {
  return (
    <section
      id="signals"
      data-testid="hero-stats"
      className="relative py-10 md:py-14 hairline-t"
    >
      <div className="max-w-[1400px] mx-auto px-4 sm:px-6 md:px-10">
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-40px" }}
          transition={{ duration: 0.6 }}
          className="grid grid-cols-3 gap-4 sm:gap-8 max-w-2xl"
        >
          {STATS.map(([n, l]) => (
            <div key={l} className="hairline-t pt-3">
              <div className="font-display text-2xl md:text-3xl text-white tracking-tight">{n}</div>
              <div className="mt-1 font-mono text-[10px] uppercase tracking-[0.16em] text-neutral-500">
                {l}
              </div>
            </div>
          ))}
        </motion.div>
      </div>
    </section>
  );
}
