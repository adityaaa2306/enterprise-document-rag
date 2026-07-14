"use client"

import { Card } from "@/components/ui/card"
import { Globe2, Radio } from "lucide-react"

export type RegionDecisionView = {
  selected_region_name?: string
  selected_region_id?: string
  selected_region?: {
    display_name?: string
    id?: string
    grid_zone?: string
    provider?: string
  } | null
  provider?: string
  grid_carbon_intensity_gco2_kwh?: number
  grid_zone?: string
  scheduling_mode?: string
  data_source?: string
  data_freshness?: string
  confidence?: string
  execution_status?: string
  future_support?: string
  reason?: string
  timestamp?: string
}

type Props = {
  decision?: RegionDecisionView | null
  /** Fallback when older jobs lack region_decision */
  fallbackIntensity?: number | null
  fallbackZone?: string | null
  fallbackSource?: string | null
}

function labelMode(mode?: string) {
  const m = (mode || "").toLowerCase()
  if (m.includes("carbon")) return "Carbon Optimized (future)"
  return "Single Region"
}

function labelStatus(status?: string) {
  const s = (status || "configured_region").replace(/_/g, " ")
  return s.replace(/\b\w/g, (c) => c.toUpperCase())
}

export function ExecutionRegionPanel({
  decision,
  fallbackIntensity,
  fallbackZone,
  fallbackSource,
}: Props) {
  const name =
    decision?.selected_region_name ||
    decision?.selected_region?.display_name ||
    "India"
  const provider = decision?.provider || decision?.selected_region?.provider || "electricity_maps"
  const intensity =
    decision?.grid_carbon_intensity_gco2_kwh ?? fallbackIntensity ?? null
  const zone =
    decision?.grid_zone ||
    decision?.selected_region?.grid_zone ||
    fallbackZone ||
    "—"
  const dataSource =
    decision?.data_source ||
    decision?.data_freshness ||
    (fallbackSource?.includes("electricity_maps")
      ? "live"
      : fallbackSource?.includes("fallback")
        ? "fallback"
        : "—")
  const mode = labelMode(decision?.scheduling_mode)
  const execStatus = labelStatus(decision?.execution_status)

  return (
    <Card className="p-6 bg-gradient-to-br from-card to-card/50 border-border/50 space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold flex items-center gap-2">
            <Globe2 className="w-5 h-5" />
            Execution Region
          </h3>
          <p className="text-xs text-muted-foreground mt-1">
            Carbon-aware region scheduling (single live region today)
          </p>
        </div>
        <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
          <Radio className="w-3.5 h-3.5" />
          {String(dataSource)}
        </span>
      </div>

      <dl className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
        <div>
          <dt className="text-xs text-muted-foreground">Selected Region</dt>
          <dd className="font-medium">{name}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Carbon Provider</dt>
          <dd className="font-medium">
            {provider === "electricity_maps" ? "Electricity Maps" : provider}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Grid Carbon Intensity</dt>
          <dd className="font-medium tabular-nums">
            {intensity != null && Number.isFinite(Number(intensity))
              ? `${Number(intensity).toFixed(0)} gCO₂e/kWh`
              : "—"}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Grid Zone</dt>
          <dd className="font-mono text-xs">{zone || "—"}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Scheduling Mode</dt>
          <dd className="font-medium">{mode}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Data Source</dt>
          <dd className="font-medium capitalize">{String(dataSource)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Execution Status</dt>
          <dd className="font-medium">{execStatus}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Confidence</dt>
          <dd className="font-medium capitalize">
            {decision?.confidence || "—"}
          </dd>
        </div>
      </dl>

      <div className="rounded-lg border border-border/40 bg-muted/20 px-3 py-2 text-xs text-muted-foreground space-y-1">
        <p>
          <span className="font-medium text-foreground">Future support:</span>{" "}
          Multi-region scheduling
        </p>
        <p>
          This run used the configured execution region only. The architecture
          is ready for additional regions; live global routing is not active.
        </p>
        {decision?.reason ? <p className="pt-1">{decision.reason}</p> : null}
      </div>
    </Card>
  )
}
