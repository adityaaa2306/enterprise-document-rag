"use client"

import Marquee from "react-fast-marquee";

const ITEMS = [
  ["52.1%", "carbon reduction · last run"],
  ["480", "gCO₂/kWh · grid intensity"],
  ["5", "chunks routed"],
  ["3", "model tiers active"],
  ["24 ms", "route decision latency"],
  ["8.3 g", "CO₂ baseline per doc"],
  ["3.97 g", "CO₂ optimized per doc"],
  ["us-west-2", "current execution region"],
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
