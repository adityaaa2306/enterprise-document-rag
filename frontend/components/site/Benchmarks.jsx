"use client"

import { motion } from "framer-motion"
import measured from "@/data/sequential_vs_dag.json"

const rows = measured?.rows || []
const headline = measured || {}

const benchRows = rows.filter((r) => r.sequential_wall_ms != null && r.speedup != null)
const validationRows = rows.filter((r) => r.label === "FinalReport.pdf live validation")

const METRICS = [
  {
    value: `${headline.headline?.median_speedup ?? "—"}x`,
    label: "median DAG speedup",
    note: headline.headline?.label || "vs sequential reduce",
  },
  {
    value: `${headline.headline?.best_speedup ?? "—"}x`,
    label: "best measured speedup",
    note: "same live NIM compile workload",
  },
  {
    value: String(benchRows[benchRows.length - 1]?.chunks ?? "—"),
    label: "largest bench chunk set",
    note: "orchestration scale point",
  },
  {
    value: benchRows.length
      ? `${Math.round(benchRows.reduce((s, r) => s + (r.parallel_wall_ms || 0), 0) / benchRows.length)}ms`
      : "—",
    label: "avg parallel wall",
    note: "DAG capacity pool · live",
  },
  {
    value: headline.finalreport_validation?.wall_clock_sec
      ? `${headline.finalreport_validation.wall_clock_sec}s`
      : benchRows.length
        ? `${Math.round(benchRows.reduce((s, r) => s + (r.sequential_wall_ms || 0), 0) / benchRows.length)}ms`
        : "—",
    label: headline.finalreport_validation ? "FinalReport live wall" : "avg sequential wall",
    note: headline.finalreport_validation
      ? `QVA ${headline.finalreport_validation.qva_confidence ?? "—"} · RL requeues ${headline.finalreport_validation.rate_limit_requeues ?? 0}`
      : "single-worker reduce · live",
  },
]

const maxWall = Math.max(
  1,
  ...benchRows.flatMap((r) => [r.sequential_wall_ms || 0, r.parallel_wall_ms || 0]),
  ...validationRows.map((r) => r.parallel_wall_ms || 0),
)

export default function Benchmarks() {
  return (
    <section id="benchmarks" data-testid="benchmarks-section" className="relative py-24 md:py-32 hairline-t bg-[#070707]">
      <div className="max-w-[1400px] mx-auto px-6 md:px-10">
        <div className="mb-14">
          <div className="font-mono text-[10px] uppercase tracking-[0.24em] text-neutral-500 mb-2">
            10 · Benchmarks
          </div>
          <h2 className="font-display text-3xl md:text-5xl tracking-tight text-white leading-[1.05] max-w-3xl">
            Measured Sequential vs{" "}
            <span className="italic font-serif font-light text-emerald-400">Parallel DAG.</span>
          </h2>
          <p className="mt-4 max-w-2xl text-sm text-neutral-400 font-mono leading-relaxed">
            {headline.note || "Real harness output from backend/scripts/bench_sequential_vs_dag.py"}
            {headline.generated_at ? ` · ${headline.generated_at}` : ""}
          </p>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-5 divide-x divide-y md:divide-y-0 divide-white/10 border border-white/10">
          {METRICS.map((m, i) => (
            <motion.div
              key={m.label}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: i * 0.08, duration: 0.6 }}
              className="p-6 md:p-8"
            >
              <div className="font-display text-4xl md:text-5xl text-white tracking-tighter">{m.value}</div>
              <div className="mt-3 font-mono text-[10px] uppercase tracking-[0.16em] text-neutral-500 leading-relaxed">
                {m.label}
              </div>
              {m.note && (
                <div className="mt-2 font-mono text-[10px] tracking-tight text-emerald-400/90">
                  {m.note}
                </div>
              )}
            </motion.div>
          ))}
        </div>

        <div className="mt-4 border border-white/10 bg-[#080808]">
          <div className="hairline-b px-6 py-4 flex items-center justify-between font-mono text-[10px] uppercase tracking-[0.2em]">
            <span className="text-neutral-400">Chart 01 · Wall time by chunk count (ms)</span>
            <span className="text-neutral-600">lower is better</span>
          </div>
          <div className="p-6 md:p-8 space-y-6">
            {benchRows.map((r, i) => (
              <motion.div
                key={`bench-${r.chunks}`}
                initial={{ opacity: 0, x: -20 }}
                whileInView={{ opacity: 1, x: 0 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.09, duration: 0.6 }}
                className="space-y-2"
              >
                <div className="font-mono text-[12px] uppercase tracking-[0.14em] text-neutral-300">
                  {r.chunks} chunks · {r.speedup}x speedup
                </div>
                <div className="grid grid-cols-12 items-center gap-2">
                  <div className="col-span-2 font-mono text-[10px] text-neutral-500">seq</div>
                  <div className="col-span-8 h-2 bg-white/5 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-neutral-500"
                      style={{ width: `${((r.sequential_wall_ms || 0) / maxWall) * 100}%` }}
                    />
                  </div>
                  <div className="col-span-2 font-mono text-[11px] text-neutral-400 tabular-nums text-right">
                    {Math.round(r.sequential_wall_ms || 0)}
                  </div>
                </div>
                <div className="grid grid-cols-12 items-center gap-2">
                  <div className="col-span-2 font-mono text-[10px] text-emerald-400">dag</div>
                  <div className="col-span-8 h-2 bg-white/5 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-emerald-400"
                      style={{ width: `${((r.parallel_wall_ms || 0) / maxWall) * 100}%` }}
                    />
                  </div>
                  <div className="col-span-2 font-mono text-[11px] text-emerald-400 tabular-nums text-right">
                    {Math.round(r.parallel_wall_ms || 0)}
                  </div>
                </div>
              </motion.div>
            ))}
            {validationRows.map((r, i) => (
              <motion.div
                key={`val-${r.label}-${r.chunks}`}
                initial={{ opacity: 0, x: -20 }}
                whileInView={{ opacity: 1, x: 0 }}
                viewport={{ once: true }}
                transition={{ delay: 0.2 + i * 0.09, duration: 0.6 }}
                className="space-y-2 hairline-t pt-6"
              >
                <div className="font-mono text-[12px] uppercase tracking-[0.14em] text-neutral-300">
                  {r.label || "FinalReport.pdf"} · {r.chunks} chunks · live validation
                </div>
                <div className="grid grid-cols-12 items-center gap-2">
                  <div className="col-span-2 font-mono text-[10px] text-emerald-400">dag</div>
                  <div className="col-span-8 h-2 bg-white/5 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-emerald-400"
                      style={{ width: `${((r.parallel_wall_ms || 0) / maxWall) * 100}%` }}
                    />
                  </div>
                  <div className="col-span-2 font-mono text-[11px] text-emerald-400 tabular-nums text-right">
                    {Math.round(r.parallel_wall_ms || 0)}
                  </div>
                </div>
                <div className="font-mono text-[10px] text-neutral-500 tracking-tight">
                  QVA {r.qva_confidence ?? "—"} · rate-limit requeues {r.rate_limit_requeues ?? 0} ·
                  hard-isolation {r.hard_isolation_timeouts ?? 0}
                </div>
              </motion.div>
            ))}
            {!benchRows.length && !validationRows.length && (
              <div className="font-mono text-sm text-neutral-500">
                No measured rows yet — run{" "}
                <code className="text-emerald-400">python scripts/bench_sequential_vs_dag.py</code>
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}
