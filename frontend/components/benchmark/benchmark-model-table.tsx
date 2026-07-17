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
import type { ModelChartRow } from "@/lib/benchmark-types"
import { displayParticipantName, fmtNum, fmtUsd } from "@/lib/benchmark-campaigns"
import { cn } from "@/lib/utils"

type SortKey =
  | "model"
  | "avg_latency_ms"
  | "avg_ttft_ms"
  | "avg_tokens_per_sec"
  | "avg_prompt_tokens"
  | "avg_completion_tokens"
  | "total_estimated_api_cost_usd"
  | "avg_estimated_energy_wh"
  | "avg_estimated_co2e_g"
  | "avg_quality_score"

const COLUMNS: Array<{ key: SortKey; label: string; align?: "left" | "right" }> = [
  { key: "model", label: "Model", align: "left" },
  { key: "avg_latency_ms", label: "Avg latency", align: "right" },
  { key: "avg_ttft_ms", label: "TTFT", align: "right" },
  { key: "avg_tokens_per_sec", label: "Tokens/sec", align: "right" },
  { key: "avg_prompt_tokens", label: "Prompt tok", align: "right" },
  { key: "avg_completion_tokens", label: "Completion tok", align: "right" },
  { key: "total_estimated_api_cost_usd", label: "Est. cost", align: "right" },
  { key: "avg_estimated_energy_wh", label: "Est. energy", align: "right" },
  { key: "avg_estimated_co2e_g", label: "Est. CO₂e", align: "right" },
  { key: "avg_quality_score", label: "Quality", align: "right" },
]

function cellValue(row: ModelChartRow, key: SortKey): string {
  switch (key) {
    case "model":
      return displayParticipantName(row.model)
    case "avg_latency_ms":
      return row.avg_latency_ms == null ? "—" : `${fmtNum(row.avg_latency_ms, 0)} ms`
    case "avg_ttft_ms":
      return row.avg_ttft_ms == null ? "—" : `${fmtNum(row.avg_ttft_ms, 0)} ms`
    case "avg_tokens_per_sec":
      return fmtNum(row.avg_tokens_per_sec, 1)
    case "avg_prompt_tokens":
      return fmtNum(row.avg_prompt_tokens, 1)
    case "avg_completion_tokens":
      return fmtNum(row.avg_completion_tokens, 1)
    case "total_estimated_api_cost_usd":
      return fmtUsd(row.total_estimated_api_cost_usd, 5)
    case "avg_estimated_energy_wh":
      return row.avg_estimated_energy_wh == null
        ? "—"
        : `${fmtNum(row.avg_estimated_energy_wh, 3)} Wh`
    case "avg_estimated_co2e_g":
      return row.avg_estimated_co2e_g == null
        ? "—"
        : `${fmtNum(row.avg_estimated_co2e_g, 3)} g`
    case "avg_quality_score":
      return row.avg_quality_score == null
        ? "—"
        : fmtNum(row.avg_quality_score, 1)
    default:
      return "—"
  }
}

function sortValue(row: ModelChartRow, key: SortKey): string | number {
  if (key === "model") return row.model || ""
  const v = row[key]
  return v == null ? Number.NEGATIVE_INFINITY : Number(v)
}

export function BenchmarkModelTable({ rows }: { rows: ModelChartRow[] }) {
  const [sortKey, setSortKey] = useState<SortKey>("avg_latency_ms")
  const [asc, setAsc] = useState(true)

  const sorted = useMemo(() => {
    const copy = [...rows]
    copy.sort((a, b) => {
      const av = sortValue(a, sortKey)
      const bv = sortValue(b, sortKey)
      if (typeof av === "string" && typeof bv === "string") {
        return asc ? av.localeCompare(bv) : bv.localeCompare(av)
      }
      return asc ? Number(av) - Number(bv) : Number(bv) - Number(av)
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
    <Card className="p-0 overflow-hidden bg-gradient-to-br from-card to-card/50 border-border/50">
      <div className="px-6 py-4 border-b border-border/60">
        <h3 className="text-lg font-semibold">Per-model comparison</h3>
        <p className="text-xs text-muted-foreground mt-1">
          Click any column header to sort. Values are aggregates from stored campaign artifacts.
        </p>
      </div>
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            {COLUMNS.map((col) => {
              const active = sortKey === col.key
              const Icon = !active ? ArrowUpDown : asc ? ArrowUp : ArrowDown
              return (
                <TableHead
                  key={col.key}
                  className={cn(
                    "whitespace-nowrap",
                    col.align === "right" && "text-right",
                  )}
                >
                  <button
                    type="button"
                    onClick={() => onSort(col.key)}
                    className={cn(
                      "inline-flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide",
                      "text-muted-foreground hover:text-foreground transition-colors",
                      active && "text-emerald-300",
                      col.align === "right" && "ml-auto",
                    )}
                  >
                    {col.label}
                    <Icon className="w-3.5 h-3.5 opacity-70" />
                  </button>
                </TableHead>
              )
            })}
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((row) => (
            <TableRow key={row.model} className="border-border/50">
              {COLUMNS.map((col) => (
                <TableCell
                  key={col.key}
                  className={cn(
                    "font-mono text-[13px]",
                    col.key === "model" && "font-sans font-medium text-foreground",
                    col.align === "right" && "text-right tabular-nums",
                  )}
                >
                  {cellValue(row, col.key)}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Card>
  )
}
