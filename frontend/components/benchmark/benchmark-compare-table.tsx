"use client"

import { useMemo, useState } from "react"
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Card } from "@/components/ui/card"
import type { DeltaSentiment, ModelDeltaRow } from "@/lib/benchmark-compare"
import { formatPct, sentimentClass } from "@/lib/benchmark-compare"
import { displayParticipantName, fmtMs, fmtNum, fmtUsd } from "@/lib/benchmark-campaigns"
import { cn } from "@/lib/utils"

type SortKey =
  | "model"
  | "latency_a"
  | "latency_b"
  | "latency_delta"
  | "cost_a"
  | "cost_b"
  | "cost_delta"
  | "co2e_a"
  | "co2e_b"
  | "co2e_delta"
  | "tps_a"
  | "tps_b"
  | "tps_delta"

const COLUMNS: Array<{ key: SortKey; label: string }> = [
  { key: "model", label: "Model" },
  { key: "latency_a", label: "A latency" },
  { key: "latency_b", label: "B latency" },
  { key: "latency_delta", label: "Δ latency" },
  { key: "cost_a", label: "A cost" },
  { key: "cost_b", label: "B cost" },
  { key: "cost_delta", label: "Δ cost" },
  { key: "co2e_a", label: "A CO₂e" },
  { key: "co2e_b", label: "B CO₂e" },
  { key: "co2e_delta", label: "Δ CO₂e" },
  { key: "tps_a", label: "A throughput" },
  { key: "tps_b", label: "B throughput" },
  { key: "tps_delta", label: "Δ throughput" },
]

function deltaSentiment(
  pct: number | null,
  lowerIsBetter: boolean,
): DeltaSentiment {
  if (pct == null) return "unknown"
  if (Math.abs(pct) < 2) return "neutral"
  if (lowerIsBetter) return pct < 0 ? "improved" : "regressed"
  return pct > 0 ? "improved" : "regressed"
}

function deltaCell(
  abs: number | null,
  pct: number | null,
  lowerIsBetter: boolean,
  formatAbs: (v: number) => string,
) {
  const sent = deltaSentiment(pct, lowerIsBetter)
  return (
    <span className={cn("font-mono tabular-nums", sentimentClass(sent))}>
      {abs == null ? "—" : formatAbs(abs)}{" "}
      <span className="text-[10px] opacity-80">({formatPct(pct)})</span>
    </span>
  )
}

export function BenchmarkCompareTable({ rows }: { rows: ModelDeltaRow[] }) {
  const [sortKey, setSortKey] = useState<SortKey>("latency_delta")
  const [asc, setAsc] = useState(true)

  const sorted = useMemo(() => {
    const copy = [...rows]
    copy.sort((a, b) => {
      const av = a[sortKey]
      const bv = b[sortKey]
      if (typeof av === "string" && typeof bv === "string") {
        return asc ? av.localeCompare(bv) : bv.localeCompare(av)
      }
      const an = av == null ? Number.NEGATIVE_INFINITY : Number(av)
      const bn = bv == null ? Number.NEGATIVE_INFINITY : Number(bv)
      return asc ? an - bn : bn - an
    })
    return copy
  }, [rows, sortKey, asc])

  const onSort = (key: SortKey) => {
    if (sortKey === key) setAsc((v) => !v)
    else {
      setSortKey(key)
      setAsc(key === "model")
    }
  }

  return (
    <Card className="p-6 bg-gradient-to-br from-card to-card/50 border-border/50 overflow-hidden">
      <div className="mb-4">
        <h3 className="text-lg font-semibold">Per-model comparison</h3>
        <p className="text-xs text-muted-foreground mt-1">
          Sort by any delta column. Values are aggregates from stored campaign artifacts.
        </p>
      </div>
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              {COLUMNS.map((c) => {
                const active = sortKey === c.key
                const Icon = !active ? ArrowUpDown : asc ? ArrowUp : ArrowDown
                return (
                  <TableHead key={c.key} className="whitespace-nowrap">
                    <button
                      type="button"
                      onClick={() => onSort(c.key)}
                      className="inline-flex items-center gap-1 text-[11px] uppercase tracking-wide hover:text-foreground"
                    >
                      {c.label}
                      <Icon className="w-3 h-3" />
                    </button>
                  </TableHead>
                )
              })}
            </TableRow>
          </TableHeader>
          <TableBody>
            {sorted.map((r) => (
              <TableRow key={r.model}>
                <TableCell className="font-medium">
                  {displayParticipantName(r.model)}
                </TableCell>
                <TableCell className="font-mono text-xs tabular-nums">
                  {fmtMs(r.latency_a)}
                </TableCell>
                <TableCell className="font-mono text-xs tabular-nums">
                  {fmtMs(r.latency_b)}
                </TableCell>
                <TableCell className="text-xs">
                  {deltaCell(r.latency_delta, r.latency_pct, true, (v) =>
                    `${v < 0 ? "−" : v > 0 ? "+" : ""}${Math.round(Math.abs(v)).toLocaleString()} ms`,
                  )}
                </TableCell>
                <TableCell className="font-mono text-xs tabular-nums">
                  {fmtUsd(r.cost_a, 5)}
                </TableCell>
                <TableCell className="font-mono text-xs tabular-nums">
                  {fmtUsd(r.cost_b, 5)}
                </TableCell>
                <TableCell className="text-xs">
                  {deltaCell(r.cost_delta, r.cost_pct, true, (v) =>
                    `${v < 0 ? "−" : v > 0 ? "+" : ""}${fmtUsd(Math.abs(v), 5)}`,
                  )}
                </TableCell>
                <TableCell className="font-mono text-xs tabular-nums">
                  {r.co2e_a == null ? "—" : `${fmtNum(r.co2e_a, 3)} g`}
                </TableCell>
                <TableCell className="font-mono text-xs tabular-nums">
                  {r.co2e_b == null ? "—" : `${fmtNum(r.co2e_b, 3)} g`}
                </TableCell>
                <TableCell className="text-xs">
                  {deltaCell(r.co2e_delta, r.co2e_pct, true, (v) =>
                    `${v < 0 ? "−" : v > 0 ? "+" : ""}${fmtNum(Math.abs(v), 3)} g`,
                  )}
                </TableCell>
                <TableCell className="font-mono text-xs tabular-nums">
                  {fmtNum(r.tps_a, 1)}
                </TableCell>
                <TableCell className="font-mono text-xs tabular-nums">
                  {fmtNum(r.tps_b, 1)}
                </TableCell>
                <TableCell className="text-xs">
                  {deltaCell(r.tps_delta, r.tps_pct, false, (v) =>
                    `${v < 0 ? "−" : v > 0 ? "+" : ""}${fmtNum(Math.abs(v), 1)}`,
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </Card>
  )
}
