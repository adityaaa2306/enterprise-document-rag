"use client"

import { motion } from "framer-motion"
import { ArrowDownRight, ArrowRight, ArrowUpRight } from "lucide-react"
import { Card } from "@/components/ui/card"
import type { MetricDelta } from "@/lib/benchmark-compare"
import {
  formatAbsDelta,
  formatPct,
  sentimentClass,
} from "@/lib/benchmark-compare"
import { fmtMs, fmtNum, fmtUsd } from "@/lib/benchmark-campaigns"
import { cn } from "@/lib/utils"

function formatValue(d: MetricDelta, side: "a" | "b"): string {
  const v = side === "a" ? d.a : d.b
  if (v == null) return "—"
  switch (d.unit) {
    case "ms":
      return fmtMs(v)
    case "USD":
      return fmtUsd(v, 4)
    case "tok/s":
      return `${fmtNum(v, 1)}`
    case "Wh":
      return `${fmtNum(v, 3)}`
    case "g":
      return `${fmtNum(v, 3)}`
    case "tok":
      return Math.round(v).toLocaleString()
    default:
      return fmtNum(v, 2)
  }
}

function TrendIcon({ sentiment, abs }: MetricDelta) {
  if (sentiment === "unknown" || abs == null || abs === 0) {
    return <ArrowRight className="w-4 h-4 text-muted-foreground" />
  }
  const Icon = abs < 0 ? ArrowDownRight : ArrowUpRight
  return <Icon className={cn("w-4 h-4", sentimentClass(sentiment))} />
}

export function BenchmarkCompareKpis({ deltas }: { deltas: MetricDelta[] }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-3">
      {deltas.map((d, i) => (
        <motion.div
          key={d.key}
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.03 * i, duration: 0.35 }}
        >
          <Card className="p-4 h-full bg-gradient-to-br from-card to-card/40 border-border/50">
            <div className="flex items-start justify-between gap-2 mb-3">
              <p className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
                {d.label}
              </p>
              <TrendIcon {...d} />
            </div>
            <p
              className={cn(
                "text-2xl font-semibold tabular-nums tracking-tight",
                sentimentClass(d.sentiment),
              )}
            >
              {d.pct == null
                ? "—"
                : `${d.abs != null && d.abs < 0 ? "↓" : d.abs != null && d.abs > 0 ? "↑" : "→"} ${fmtNum(Math.abs(d.pct), 0)}%`}
            </p>
            <p className="mt-2 text-xs text-muted-foreground font-mono tabular-nums">
              {formatValue(d, "a")} → {formatValue(d, "b")}
              {d.unit === "tok/s" ? " tok/s" : d.unit === "Wh" ? " Wh" : d.unit === "g" ? " g" : ""}
            </p>
            <p className="mt-1 text-[11px] text-muted-foreground/80 font-mono">
              {formatAbsDelta(d)} · {formatPct(d.pct)}
            </p>
          </Card>
        </motion.div>
      ))}
    </div>
  )
}
