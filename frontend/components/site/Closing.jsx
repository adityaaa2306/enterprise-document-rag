"use client"

import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowUpRight, ArrowRight } from "lucide-react";

export default function Closing() {
  return (
    <section id="closing" data-testid="closing-section" className="relative py-28 md:py-40 hairline-t overflow-hidden">
      <div className="absolute inset-0 grid-bg opacity-30 pointer-events-none" />
      {/* radial glow */}
      <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] rounded-full pointer-events-none"
           style={{ background: "radial-gradient(circle, rgba(16,185,129,0.08), transparent 70%)" }} />

      <div className="relative max-w-[1400px] mx-auto px-6 md:px-10">
        <div className="max-w-3xl mx-auto text-center">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.7 }}
            className="font-mono text-[10px] uppercase tracking-[0.24em] text-emerald-400 mb-6"
          >
            ✦ End of transmission
          </motion.div>
          <motion.h2
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ delay: 0.1, duration: 0.8 }}
            className="font-display text-4xl md:text-6xl lg:text-7xl tracking-tighter text-white leading-[1.02]"
          >
            Explore the live<br />
            <span className="italic font-serif font-light text-emerald-400">demo.</span>
          </motion.h2>
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ delay: 0.25, duration: 0.7 }}
            className="mt-12 flex flex-wrap justify-center items-center gap-4"
          >
            <Link
              href="/new-job"
              data-testid="closing-cta-primary"
              className="group inline-flex items-center gap-2 bg-emerald-500 text-black px-6 py-4 font-mono text-[11px] uppercase tracking-[0.18em] hover:bg-emerald-400 transition-colors emerald-glow"
            >
              Explore the live demo
              <ArrowUpRight className="w-4 h-4 group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition-transform" strokeWidth={2} />
            </Link>
            <a
              href="#system"
              data-testid="closing-cta-secondary"
              className="group inline-flex items-center gap-2 border border-white/20 text-white px-6 py-4 font-mono text-[11px] uppercase tracking-[0.18em] hover:border-white/50 transition-colors"
            >
              Read the full architecture
              <ArrowRight className="w-4 h-4 group-hover:translate-x-0.5 transition-transform" strokeWidth={2} />
            </a>
          </motion.div>
        </div>
      </div>
    </section>
  );
}
