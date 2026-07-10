export type RoutingPreference =
  | "automatic"
  | "fastest"
  | "lowest_cost"
  | "lowest_carbon"
  | "highest_quality"

export const ROUTING_PREFERENCE_OPTIONS: {
  id: RoutingPreference
  label: string
  description: string
}[] = [
  {
    id: "automatic",
    label: "Automatic (Recommended)",
    description: "Balanced weights — CRE and the Intelligent Router choose freely.",
  },
  {
    id: "fastest",
    label: "Prefer Fastest",
    description: "Favor lower latency and availability. Never below capability floors.",
  },
  {
    id: "lowest_cost",
    label: "Prefer Lowest Cost",
    description: "Favor cheaper tiers when capability allows.",
  },
  {
    id: "lowest_carbon",
    label: "Prefer Lowest Carbon",
    description: "Increase carbon weight in utility ranking only.",
  },
  {
    id: "highest_quality",
    label: "Prefer Highest Quality",
    description: "Favor accuracy and capacity when multiple tiers qualify.",
  },
]
