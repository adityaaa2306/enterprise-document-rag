"use client"

import { Leaf } from "lucide-react";

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
                green/agentic
              </span>
            </div>
            <p className="mt-4 text-sm text-neutral-500 max-w-xs leading-relaxed">
              A document processing pipeline that reasons about its own carbon cost.
            </p>
          </div>
          <div className="md:col-span-8 grid grid-cols-2 md:grid-cols-4 gap-6 font-mono text-[10px] uppercase tracking-[0.18em]">
            {[
              { title: "System", links: ["Overview", "Pipeline", "Routing"] },
              { title: "Research", links: ["Methodology", "Benchmarks", "FAQ"] },
              { title: "Code", links: ["GitHub", "Paper draft", "Changelog"] },
              { title: "Contact", links: ["Email", "LinkedIn", "GScholar"] },
            ].map((col) => (
              <div key={col.title}>
                <div className="text-neutral-500 mb-3">{col.title}</div>
                <ul className="space-y-2">
                  {col.links.map((l) => (
                    <li key={l}>
                      <a href="#" className="text-neutral-300 hover:text-emerald-400 transition-colors">
                        {l}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
        <div className="hairline-t mt-14 pt-6 flex flex-wrap items-center justify-between gap-3 font-mono text-[10px] uppercase tracking-[0.18em] text-neutral-600">
          <div>© {new Date().getFullYear()} · Green Agentic Systems</div>
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
