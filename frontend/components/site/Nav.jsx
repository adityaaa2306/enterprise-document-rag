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
      className="fixed top-0 left-0 right-0 z-50 backdrop-blur-md bg-[#050505]/70 hairline-b"
      data-testid="site-nav"
    >
      <div className="max-w-[1400px] mx-auto px-6 md:px-10 flex items-center justify-between h-14">
        <a href="#top" className="flex items-center gap-2.5 group" data-testid="nav-logo">
          <div className="relative">
            <div className="w-6 h-6 border border-white/20 flex items-center justify-center">
              <Leaf className="w-3.5 h-3.5 text-emerald-400" strokeWidth={1.5} />
            </div>
          </div>
          <span className="font-mono text-[11px] tracking-[0.18em] uppercase text-neutral-300">
            green/agentic
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
        <div className="flex items-center gap-3 md:gap-4">
          <Link
            href="/dashboard"
            data-testid="nav-dashboard"
            className="hidden sm:inline font-mono text-[11px] tracking-[0.14em] uppercase text-neutral-500 hover:text-white transition-colors"
          >
            Dashboard
          </Link>
          <Link
            href="/login"
            prefetch
            data-testid="nav-login"
            className="font-mono text-[11px] tracking-[0.14em] uppercase text-neutral-500 hover:text-white transition-colors"
          >
            Login
          </Link>
          <LiveDemoLink
            data-testid="nav-cta"
            className="font-mono text-[11px] tracking-[0.14em] uppercase px-3 py-1.5 border border-emerald-500/40 text-emerald-400 hover:bg-emerald-500 hover:text-black transition-colors"
          >
            Live demo →
          </LiveDemoLink>
        </div>
      </div>
    </motion.header>
  );
}
