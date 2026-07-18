"use client"

import Link from "next/link";
import { motion } from "framer-motion";
import { Leaf } from "lucide-react";
import { LiveDemoLink } from "@/components/live-demo-link";

export default function Nav() {
  const links = [
    { label: "System", href: "#system" },
    { label: "Routing", href: "#routing" },
    { label: "Methodology", href: "#methodology" },
    { label: "Benchmarks", href: "#benchmarks" },
    { label: "FAQ", href: "#faq" },
  ];
  return (
    <motion.header
      initial={{ y: -30, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
      className="fixed top-0 left-0 right-0 z-50 backdrop-blur-md bg-[#050505]/70 hairline-b pt-[env(safe-area-inset-top)]"
      data-testid="site-nav"
    >
      <div className="max-w-[1400px] mx-auto px-3 sm:px-6 md:px-10 flex items-center justify-between gap-2 h-11 md:h-14">
        <a href="#top" className="flex items-center gap-1.5 sm:gap-2.5 group min-w-0 shrink" data-testid="nav-logo">
          <div className="relative shrink-0">
            <div className="w-5 h-5 md:w-6 md:h-6 border border-white/20 flex items-center justify-center">
              <Leaf className="w-3 h-3 md:w-3.5 md:h-3.5 text-emerald-400" strokeWidth={1.5} />
            </div>
          </div>
          <span className="font-mono text-[10px] md:text-[11px] tracking-[0.14em] md:tracking-[0.18em] uppercase text-neutral-300 truncate">
            CarbonRoute AI
          </span>
        </a>
        <nav className="hidden md:flex items-center gap-8">
          {links.map((l) => (
            <a
              key={l.href}
              href={l.href}
              data-testid={`nav-link-${l.label.toLowerCase()}`}
              className="font-mono text-[11px] tracking-[0.14em] uppercase text-neutral-500 hover:text-white transition-colors"
            >
              {l.label}
            </a>
          ))}
        </nav>
        <div className="flex items-center gap-2 sm:gap-3 md:gap-4 shrink-0">
          <Link
            href="/login"
            prefetch
            data-testid="nav-login"
            className="font-mono text-[10px] md:text-[11px] tracking-[0.12em] md:tracking-[0.14em] uppercase text-neutral-500 hover:text-white transition-colors"
          >
            Login
          </Link>
          <LiveDemoLink
            nextPath="/new-job"
            data-testid="nav-cta"
            className="font-mono text-[9px] sm:text-[10px] md:text-[11px] tracking-[0.12em] md:tracking-[0.14em] uppercase px-2 py-1 sm:px-2.5 sm:py-1.5 md:px-3 border border-emerald-500/40 text-emerald-400 hover:bg-emerald-500 hover:text-black transition-colors whitespace-nowrap"
          >
            Live demo →
          </LiveDemoLink>
        </div>
      </div>
    </motion.header>
  );
}
