"use client"

import { Leaf } from "lucide-react";

const GITHUB_URL = "https://github.com/adityaaa2306/enterprise-document-rag";
const LINKEDIN_URL = "https://www.linkedin.com/in/aditya-nimbalkar-b46405239/";
const EMAIL = "mailto:adityanimbalkar2306@gmail.com";
const PAPER_URL = `${GITHUB_URL}/blob/main/docs/architecture.md`;

const columns = [
  {
    title: "System",
    links: [
      { label: "Overview", href: "#system" },
      { label: "Pipeline", href: "#pipeline" },
      { label: "Routing", href: "#routing" },
    ],
  },
  {
    title: "Research",
    links: [
      { label: "Methodology", href: "#methodology" },
      { label: "Benchmarks", href: "#benchmarks" },
      { label: "FAQ", href: "#faq" },
    ],
  },
  {
    title: "Code",
    links: [
      { label: "GitHub", href: GITHUB_URL, external: true },
      { label: "Paper draft", href: PAPER_URL, external: true },
    ],
  },
  {
    title: "Contact",
    links: [
      { label: "Email", href: EMAIL },
      { label: "LinkedIn", href: LINKEDIN_URL, external: true },
    ],
  },
];

export default function Footer() {
  return (
    <footer data-testid="site-footer" className="relative hairline-t py-14 bg-[#050505]">
      <div className="max-w-[1400px] mx-auto px-6 md:px-10">
        <div className="grid grid-cols-1 md:grid-cols-12 gap-8 items-start">
          <div className="md:col-span-4">
            <div className="flex items-center gap-2.5">
              <div className="w-6 h-6 border border-white/20 flex items-center justify-center">
                <Leaf className="w-3.5 h-3.5 text-emerald-400" strokeWidth={1.5} />
              </div>
              <span className="font-mono text-[11px] tracking-[0.18em] uppercase text-neutral-300">
                EcoRoute AI
              </span>
            </div>
            <p className="mt-4 text-sm text-neutral-500 max-w-xs leading-relaxed">
              A document processing pipeline that reasons about its own carbon cost.
            </p>
          </div>
          <div className="md:col-span-8 grid grid-cols-2 md:grid-cols-4 gap-6 font-mono text-[10px] uppercase tracking-[0.18em]">
            {columns.map((col) => (
              <div key={col.title}>
                <div className="text-neutral-500 mb-3">{col.title}</div>
                <ul className="space-y-2">
                  {col.links.map((l) => (
                    <li key={l.label}>
                      <a
                        href={l.href}
                        {...(l.external
                          ? { target: "_blank", rel: "noopener noreferrer" }
                          : {})}
                        className="text-neutral-300 hover:text-emerald-400 transition-colors"
                      >
                        {l.label}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
        <div className="hairline-t mt-14 pt-6 flex flex-wrap items-center justify-between gap-3 font-mono text-[10px] uppercase tracking-[0.18em] text-neutral-600">
          <div>© {new Date().getFullYear()} · EcoRoute AI</div>
          <div className="flex items-center gap-4">
            <span>build 2.4.1</span>
            <span>·</span>
            <span className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 bg-emerald-400 rounded-full animate-pulse" />
              live · India (single-region)
            </span>
          </div>
        </div>
      </div>
    </footer>
  );
}
