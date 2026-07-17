"use client"

import Marquee from "react-fast-marquee";

const ITEMS = [
  ["52.1%", "carbon reduction · featured run"],
  ["NIM", "Llama 3.2 3B · Ministral 14B · Llama 3.3 70B"],
  ["3", "model tiers · Light / Medium / Heavy"],
  ["CRE + QVA", "capability floors · bounded escalation"],
  ["8.3 g", "CO₂e baseline · Document Processing"],
  ["3.97 g", "CO₂e optimized · Document Processing"],
  ["India", "single-region live · Electricity Maps"],
  ["RAG ≠ ingest", "Interactive RAG carbon tracked separately"],
];

export default function Ticker() {
  return (
    <div data-testid="ticker" className="relative hairline-t hairline-b bg-[#080808] marquee-fade overflow-hidden">
      <Marquee gradient={false} speed={38} pauseOnHover>
        {ITEMS.concat(ITEMS).map((item, i) => (
          <div key={i} className="flex items-center gap-3 px-8 py-3">
            <span className="font-mono text-white text-[13px] tracking-tight">{item[0]}</span>
            <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-neutral-500">{item[1]}</span>
            <span className="w-1 h-1 rounded-full bg-emerald-400/70 ml-4" />
          </div>
        ))}
      </Marquee>
    </div>
  );
}
