/**
 * Solid colors for Recharts — never wrap oklch CSS vars in hsl(), which
 * produces invalid paint and falls back to near-black (invisible on dark cards).
 */

import type { CSSProperties } from "react"

export const CHART_TEAL = "#14B8A6"
export const CHART_AMBER = "#F59E0B"
export const CHART_CORAL = "#F43F5E"
export const CHART_EMERALD = "#10B981"

/** Axis / tick label text — high contrast on dark card backgrounds */
export const CHART_TICK = "#E5E5E5"
export const CHART_TICK_MUTED = "#A3A3A3"
export const CHART_GRID = "rgba(255,255,255,0.10)"
export const CHART_AXIS_LINE = "rgba(255,255,255,0.18)"

export const CHART_AXIS_TICK = {
  fill: CHART_TICK,
  fontSize: 11,
} as const

export const CHART_AXIS_TICK_SM = {
  fill: CHART_TICK,
  fontSize: 10,
} as const

export const CHART_LEGEND_STYLE: CSSProperties = {
  color: CHART_TICK,
  fontSize: 12,
  cursor: "pointer",
}

export const CHART_TOOLTIP_BOX =
  "rounded-lg border border-white/15 bg-[#0c0c0c]/95 px-3.5 py-2.5 text-xs text-white shadow-2xl backdrop-blur-sm"
