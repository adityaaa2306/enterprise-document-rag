/**
 * Read-only campaign comparison helpers.
 * All values derived from stored campaign artifacts — no execution.
 */
import type {
  CampaignBundle,
  CampaignIndexEntry,
  ModelChartRow,
  QuestionExplorerItem,
  QuestionRun,
} from "@/lib/benchmark-types"
import { fmtDate, fmtMs, fmtNum, fmtUsd, isSuccessfulCampaign } from "@/lib/benchmark-campaigns"

export type DeltaSentiment = "improved" | "regressed" | "neutral" | "unknown"

export type MetricDelta = {
  key: string
  label: string
  unit: string
  a: number | null
  b: number | null
  abs: number | null
  pct: number | null
  /** true = lower B vs A is an improvement */
  lowerIsBetter: boolean
  sentiment: DeltaSentiment
}

export type MethodologyCheck = {
  field: string
  label: string
  a: string
  b: string
  match: boolean
}

export type ModelDeltaRow = {
  model: string
  latency_a: number | null
  latency_b: number | null
  latency_delta: number | null
  latency_pct: number | null
  cost_a: number | null
  cost_b: number | null
  cost_delta: number | null
  cost_pct: number | null
  co2e_a: number | null
  co2e_b: number | null
  co2e_delta: number | null
  co2e_pct: number | null
  tps_a: number | null
  tps_b: number | null
  tps_delta: number | null
  tps_pct: number | null
}

export type CampaignAggregates = {
  avg_latency_ms: number | null
  avg_ttft_ms: number | null
  avg_tokens_per_sec: number | null
  total_api_cost_usd: number | null
  avg_estimated_energy_wh: number | null
  avg_estimated_co2e_g: number | null
  total_estimated_co2e_g: number | null
  total_prompt_tokens: number | null
  total_completion_tokens: number | null
  total_tokens: number | null
  total_runtime_sec: number | null
}

export type CompareExportPayload = {
  schema_version: string
  exported_at_utc: string
  baseline: {
    campaign_id: string
    label: string
    benchmark_version: string
    retrieval_version: string
    prompt_version: string
    suite: string
    timestamp_utc: string
  }
  comparison: {
    campaign_id: string
    label: string
    benchmark_version: string
    retrieval_version: string
    prompt_version: string
    suite: string
    timestamp_utc: string
  }
  methodology: MethodologyCheck[]
  methodology_compatible: boolean
  kpi_deltas: MetricDelta[]
  executive_summary: string
  per_model: ModelDeltaRow[]
}

const NEUTRAL_PCT = 2

function num(v: unknown): number | null {
  if (v == null || v === "") return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

export function weightedMean(
  rows: ModelChartRow[],
  key: keyof ModelChartRow,
): number | null {
  let sum = 0
  let weight = 0
  for (const row of rows) {
    const v = num(row[key])
    if (v == null) continue
    const w = row.n_ok || row.n_runs || 1
    sum += v * w
    weight += w
  }
  return weight > 0 ? sum / weight : null
}

export function aggregateCampaign(bundle: CampaignBundle): CampaignAggregates {
  const rows = bundle.dashboard.table?.per_model || []
  const totals = bundle.dashboard.totals
  const totalCo2e = rows.reduce((acc, r) => {
    if (r.total_estimated_co2e_g != null) {
      return acc + (num(r.total_estimated_co2e_g) || 0)
    }
    const n = Math.max(1, Number(r.n_ok || r.n_runs || 1))
    return acc + (num(r.avg_estimated_co2e_g) || 0) * n
  }, 0)
  return {
    avg_latency_ms: weightedMean(rows, "avg_latency_ms"),
    avg_ttft_ms: weightedMean(rows, "avg_ttft_ms"),
    avg_tokens_per_sec: weightedMean(rows, "avg_tokens_per_sec"),
    total_api_cost_usd:
      num(totals?.total_api_cost_usd) ??
      num(bundle.metadata.total_api_cost_usd) ??
      rows.reduce((acc, r) => acc + (num(r.total_estimated_api_cost_usd) || 0), 0),
    avg_estimated_energy_wh: weightedMean(rows, "avg_estimated_energy_wh"),
    avg_estimated_co2e_g: weightedMean(rows, "avg_estimated_co2e_g"),
    total_estimated_co2e_g: rows.length ? totalCo2e : null,
    total_prompt_tokens: num(totals?.total_prompt_tokens),
    total_completion_tokens: num(totals?.total_completion_tokens),
    total_tokens: num(totals?.total_tokens),
    total_runtime_sec:
      num(totals?.total_runtime_sec) ?? num(bundle.metadata.total_runtime_sec),
  }
}

export function computeDelta(
  a: number | null,
  b: number | null,
  lowerIsBetter: boolean,
): Pick<MetricDelta, "abs" | "pct" | "sentiment"> {
  if (a == null || b == null) {
    return { abs: null, pct: null, sentiment: "unknown" }
  }
  const abs = b - a
  const pct = a === 0 ? (b === 0 ? 0 : null) : (abs / Math.abs(a)) * 100
  if (pct == null) return { abs, pct, sentiment: "unknown" }
  if (Math.abs(pct) < NEUTRAL_PCT) {
    return { abs, pct, sentiment: "neutral" }
  }
  const improved = lowerIsBetter ? abs < 0 : abs > 0
  return { abs, pct, sentiment: improved ? "improved" : "regressed" }
}

export function buildKpiDeltas(
  a: CampaignAggregates,
  b: CampaignAggregates,
): MetricDelta[] {
  const specs: Array<{
    key: keyof CampaignAggregates
    label: string
    unit: string
    lowerIsBetter: boolean
  }> = [
    { key: "avg_latency_ms", label: "Average latency", unit: "ms", lowerIsBetter: true },
    { key: "avg_ttft_ms", label: "TTFT", unit: "ms", lowerIsBetter: true },
    {
      key: "avg_tokens_per_sec",
      label: "Throughput",
      unit: "tok/s",
      lowerIsBetter: false,
    },
    {
      key: "total_api_cost_usd",
      label: "Estimated cost",
      unit: "USD",
      lowerIsBetter: true,
    },
    {
      key: "avg_estimated_energy_wh",
      label: "Estimated energy",
      unit: "Wh",
      lowerIsBetter: true,
    },
    {
      key: "avg_estimated_co2e_g",
      label: "Estimated CO₂e",
      unit: "g",
      lowerIsBetter: true,
    },
    {
      key: "total_tokens",
      label: "Token usage",
      unit: "tok",
      lowerIsBetter: true,
    },
  ]

  return specs.map((s) => {
    const av = a[s.key]
    const bv = b[s.key]
    const d = computeDelta(av, bv, s.lowerIsBetter)
    return {
      key: s.key,
      label: s.label,
      unit: s.unit,
      a: av,
      b: bv,
      lowerIsBetter: s.lowerIsBetter,
      ...d,
    }
  })
}

export function checkMethodology(
  baseline: CampaignBundle,
  comparison: CampaignBundle,
): MethodologyCheck[] {
  const fields: Array<{ field: string; label: string; a: string; b: string }> = [
    {
      field: "benchmark_version",
      label: "Benchmark version",
      a: baseline.metadata.benchmark_version || baseline.config.benchmark_version || "—",
      b:
        comparison.metadata.benchmark_version ||
        comparison.config.benchmark_version ||
        "—",
    },
    {
      field: "prompt_version",
      label: "Prompt version",
      a: baseline.metadata.prompt_version || baseline.config.prompt_version || "—",
      b: comparison.metadata.prompt_version || comparison.config.prompt_version || "—",
    },
    {
      field: "retrieval_version",
      label: "Retrieval version",
      a: baseline.metadata.retrieval_version || baseline.config.retrieval_version || "—",
      b:
        comparison.metadata.retrieval_version ||
        comparison.config.retrieval_version ||
        "—",
    },
    {
      field: "suite",
      label: "Suite / methodology",
      a: baseline.metadata.suite || baseline.config.suite || "—",
      b: comparison.metadata.suite || comparison.config.suite || "—",
    },
    {
      field: "document_id",
      label: "Document",
      a: baseline.metadata.document_id || baseline.config.document_id || "—",
      b: comparison.metadata.document_id || comparison.config.document_id || "—",
    },
  ]
  return fields.map((f) => ({ ...f, match: f.a === f.b }))
}

export function buildModelDeltaRows(
  baseline: CampaignBundle,
  comparison: CampaignBundle,
): ModelDeltaRow[] {
  const aMap = new Map(
    (baseline.dashboard.table?.per_model || []).map((r) => [r.model, r]),
  )
  const bMap = new Map(
    (comparison.dashboard.table?.per_model || []).map((r) => [r.model, r]),
  )
  const models = Array.from(new Set([...aMap.keys(), ...bMap.keys()])).sort()

  return models.map((model) => {
    const ar = aMap.get(model)
    const br = bMap.get(model)
    const la = num(ar?.avg_latency_ms)
    const lb = num(br?.avg_latency_ms)
    const ca = num(ar?.total_estimated_api_cost_usd)
    const cb = num(br?.total_estimated_api_cost_usd)
    const ea = num(ar?.avg_estimated_co2e_g)
    const eb = num(br?.avg_estimated_co2e_g)
    const ta = num(ar?.avg_tokens_per_sec)
    const tb = num(br?.avg_tokens_per_sec)
    const ld = computeDelta(la, lb, true)
    const cd = computeDelta(ca, cb, true)
    const ed = computeDelta(ea, eb, true)
    const td = computeDelta(ta, tb, false)
    return {
      model,
      latency_a: la,
      latency_b: lb,
      latency_delta: ld.abs,
      latency_pct: ld.pct,
      cost_a: ca,
      cost_b: cb,
      cost_delta: cd.abs,
      cost_pct: cd.pct,
      co2e_a: ea,
      co2e_b: eb,
      co2e_delta: ed.abs,
      co2e_pct: ed.pct,
      tps_a: ta,
      tps_b: tb,
      tps_delta: td.abs,
      tps_pct: td.pct,
    }
  })
}

function fmtMetricValue(key: string, value: number | null): string {
  if (value == null) return "—"
  switch (key) {
    case "avg_latency_ms":
    case "avg_ttft_ms":
      return fmtMs(value)
    case "total_api_cost_usd":
      return fmtUsd(value, 5)
    case "avg_tokens_per_sec":
      return `${fmtNum(value, 1)} tok/s`
    case "avg_estimated_energy_wh":
      return `${fmtNum(value, 3)} Wh`
    case "avg_estimated_co2e_g":
      return `${fmtNum(value, 3)} g`
    case "total_tokens":
    case "total_prompt_tokens":
    case "total_completion_tokens":
      return Math.round(value).toLocaleString()
    default:
      return fmtNum(value, 2)
  }
}

export function formatPct(pct: number | null): string {
  if (pct == null || Number.isNaN(pct)) return "—"
  const sign = pct > 0 ? "+" : pct < 0 ? "−" : ""
  return `${sign}${fmtNum(Math.abs(pct), 1)}%`
}

export function formatAbsDelta(delta: MetricDelta): string {
  if (delta.abs == null) return "—"
  const sign = delta.abs > 0 ? "+" : delta.abs < 0 ? "−" : ""
  const mag = Math.abs(delta.abs)
  switch (delta.unit) {
    case "ms":
      return `${sign}${Math.round(mag).toLocaleString()} ms`
    case "USD":
      return `${sign}${fmtUsd(mag, 5).replace("$", "$")}`
    case "tok/s":
      return `${sign}${fmtNum(mag, 1)} tok/s`
    case "Wh":
      return `${sign}${fmtNum(mag, 3)} Wh`
    case "g":
      return `${sign}${fmtNum(mag, 3)} g`
    case "tok":
      return `${sign}${Math.round(mag).toLocaleString()}`
    default:
      return `${sign}${fmtNum(mag, 2)}`
  }
}

export function buildEvolutionSummaryClean(
  baseline: CampaignBundle,
  comparison: CampaignBundle,
  deltas: MetricDelta[],
): string {
  const aLabel =
    baseline.index.label || `v${baseline.metadata.benchmark_version}`
  const byKey = Object.fromEntries(deltas.map((d) => [d.key, d])) as Record<
    string,
    MetricDelta
  >

  const changeClause = (d: MetricDelta | undefined, label: string) => {
    if (!d || d.pct == null || d.sentiment === "unknown") return null
    if (d.sentiment === "neutral") return `${label} remained nearly unchanged`
    const verb =
      d.sentiment === "improved"
        ? d.lowerIsBetter
          ? "decreased"
          : "increased"
        : d.lowerIsBetter
          ? "increased"
          : "decreased"
    return `${label} ${verb} by ${fmtNum(Math.abs(d.pct), 1)}%`
  }

  const models = comparison.dashboard.table?.per_model || []
  let balanceModel = "the evaluated models"
  if (models.length) {
    const lats = models.map((m) => num(m.avg_latency_ms)).filter((v): v is number => v != null)
    const costs = models
      .map((m) => num(m.total_estimated_api_cost_usd))
      .filter((v): v is number => v != null)
    const maxL = Math.max(...lats, 1)
    const maxC = Math.max(...costs, 1e-9)
    let best = Number.POSITIVE_INFINITY
    for (const m of models) {
      const l = num(m.avg_latency_ms)
      const c = num(m.total_estimated_api_cost_usd)
      if (l == null || c == null) continue
      const score = l / maxL + c / maxC
      if (score < best) {
        best = score
        balanceModel = m.model
      }
    }
  }

  const parts = [
    changeClause(byKey.avg_latency_ms, "average latency"),
    changeClause(byKey.avg_estimated_co2e_g, "estimated CO₂e"),
  ].filter(Boolean)

  const head =
    parts.length >= 2
      ? `Compared with ${aLabel}, ${parts[0]} while ${parts[1]}.`
      : parts.length === 1
        ? `Compared with ${aLabel}, ${parts[0]}.`
        : `Compared with ${aLabel}, key metrics were only partially available.`

  const tput = changeClause(byKey.avg_tokens_per_sec, "Throughput")
  const cost = changeClause(byKey.total_api_cost_usd, "benchmark cost")
  const mid = `${balanceModel} was the best overall balance of latency and cost in the comparison campaign.`
  const tail = [tput, cost].filter(Boolean).join(", while ")
  return [head, mid, tail ? `${tail}.` : ""].filter(Boolean).join(" ")
}

export function pickCompareDefaults(rows: CampaignIndexEntry[]): {
  baselineId: string
  comparisonId: string
} | null {
  if (!rows.length) return null
  const chrono = [...rows].sort((a, b) => {
    const ta = Date.parse(a.timestamp_utc || "") || 0
    const tb = Date.parse(b.timestamp_utc || "") || 0
    return ta - tb
  })
  const ok = chrono.filter(isSuccessfulCampaign)
  if (ok.length >= 2) {
    return {
      baselineId: ok[ok.length - 2].campaign_id,
      comparisonId: ok[ok.length - 1].campaign_id,
    }
  }
  if (chrono.length >= 2) {
    const newestOk = [...chrono].reverse().find(isSuccessfulCampaign)
    return {
      baselineId: chrono[0].campaign_id,
      comparisonId: (newestOk || chrono[chrono.length - 1]).campaign_id,
    }
  }
  return {
    baselineId: chrono[0].campaign_id,
    comparisonId: chrono[0].campaign_id,
  }
}

export function unionModels(
  a: CampaignBundle,
  b: CampaignBundle,
): string[] {
  return Array.from(
    new Set([
      ...(a.dashboard.models || []),
      ...(b.dashboard.models || []),
      ...(a.dashboard.table?.per_model || []).map((r) => r.model),
      ...(b.dashboard.table?.per_model || []).map((r) => r.model),
    ]),
  ).sort()
}

export function modelMetric(
  bundle: CampaignBundle,
  model: string,
  key: keyof ModelChartRow,
): number | null {
  const row = (bundle.dashboard.table?.per_model || []).find((r) => r.model === model)
  return row ? num(row[key]) : null
}

export function alignedQuestions(
  a: CampaignBundle,
  b: CampaignBundle,
): Array<{ question: string; a?: QuestionExplorerItem; b?: QuestionExplorerItem }> {
  const mapA = new Map(a.questions.map((q) => [q.question, q]))
  const mapB = new Map(b.questions.map((q) => [q.question, q]))
  const keys = Array.from(new Set([...mapA.keys(), ...mapB.keys()]))
  return keys.map((question) => ({
    question,
    a: mapA.get(question),
    b: mapB.get(question),
  }))
}

export function runByModel(
  item: QuestionExplorerItem | undefined,
  model: string,
): QuestionRun | undefined {
  return (item?.model_runs || []).find((r) => r.model === model)
}

export function buildExportPayload(
  baseline: CampaignBundle,
  comparison: CampaignBundle,
): CompareExportPayload {
  const aAgg = aggregateCampaign(baseline)
  const bAgg = aggregateCampaign(comparison)
  const kpi = buildKpiDeltas(aAgg, bAgg)
  const methodology = checkMethodology(baseline, comparison)
  return {
    schema_version: "1.0.0",
    exported_at_utc: new Date().toISOString(),
    baseline: {
      campaign_id: baseline.index.campaign_id,
      label: baseline.index.label,
      benchmark_version: baseline.metadata.benchmark_version,
      retrieval_version: baseline.metadata.retrieval_version,
      prompt_version: baseline.metadata.prompt_version,
      suite: baseline.metadata.suite,
      timestamp_utc: baseline.metadata.timestamp_utc,
    },
    comparison: {
      campaign_id: comparison.index.campaign_id,
      label: comparison.index.label,
      benchmark_version: comparison.metadata.benchmark_version,
      retrieval_version: comparison.metadata.retrieval_version,
      prompt_version: comparison.metadata.prompt_version,
      suite: comparison.metadata.suite,
      timestamp_utc: comparison.metadata.timestamp_utc,
    },
    methodology,
    methodology_compatible: methodology.every((m) => m.match),
    kpi_deltas: kpi,
    executive_summary: buildEvolutionSummaryClean(baseline, comparison, kpi),
    per_model: buildModelDeltaRows(baseline, comparison),
  }
}

export function exportToMarkdown(payload: CompareExportPayload): string {
  const lines: string[] = [
    `# Campaign comparison`,
    ``,
    `Exported: ${payload.exported_at_utc}`,
    ``,
    `## Campaigns`,
    ``,
    `| Role | Label | Campaign ID | Benchmark | Prompt | Retrieval | Suite | Timestamp |`,
    `| --- | --- | --- | --- | --- | --- | --- | --- |`,
    `| Baseline | ${payload.baseline.label} | \`${payload.baseline.campaign_id}\` | ${payload.baseline.benchmark_version} | ${payload.baseline.prompt_version} | ${payload.baseline.retrieval_version} | ${payload.baseline.suite} | ${fmtDate(payload.baseline.timestamp_utc)} |`,
    `| Comparison | ${payload.comparison.label} | \`${payload.comparison.campaign_id}\` | ${payload.comparison.benchmark_version} | ${payload.comparison.prompt_version} | ${payload.comparison.retrieval_version} | ${payload.comparison.suite} | ${fmtDate(payload.comparison.timestamp_utc)} |`,
    ``,
    `## Methodology compatibility`,
    ``,
    payload.methodology_compatible
      ? `All checked methodology fields match.`
      : `Warning: one or more methodology fields differ — comparisons may not be directly comparable.`,
    ``,
    ...payload.methodology.map(
      (m) =>
        `- **${m.label}**: \`${m.a}\` vs \`${m.b}\` — ${m.match ? "match" : "DIFFERS"}`,
    ),
    ``,
    `## Executive summary`,
    ``,
    payload.executive_summary,
    ``,
    `## KPI deltas`,
    ``,
    `| Metric | Baseline | Comparison | Δ abs | Δ % | Sentiment |`,
    `| --- | --- | --- | --- | --- | --- |`,
    ...payload.kpi_deltas.map((d) => {
      return `| ${d.label} | ${fmtMetricValue(d.key, d.a)} | ${fmtMetricValue(d.key, d.b)} | ${formatAbsDelta(d)} | ${formatPct(d.pct)} | ${d.sentiment} |`
    }),
    ``,
    `## Per-model comparison`,
    ``,
    `| Model | Lat A | Lat B | Δ lat % | Cost A | Cost B | Δ cost % | CO₂e A | CO₂e B | Δ CO₂e % | TPS A | TPS B | Δ TPS % |`,
    `| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |`,
    ...payload.per_model.map((r) => {
      return `| ${r.model} | ${fmtMs(r.latency_a)} | ${fmtMs(r.latency_b)} | ${formatPct(r.latency_pct)} | ${fmtUsd(r.cost_a, 5)} | ${fmtUsd(r.cost_b, 5)} | ${formatPct(r.cost_pct)} | ${r.co2e_a == null ? "—" : fmtNum(r.co2e_a, 3)} | ${r.co2e_b == null ? "—" : fmtNum(r.co2e_b, 3)} | ${formatPct(r.co2e_pct)} | ${fmtNum(r.tps_a, 1)} | ${fmtNum(r.tps_b, 1)} | ${formatPct(r.tps_pct)} |`
    }),
    ``,
  ]
  return lines.join("\n")
}

export function downloadText(filename: string, content: string, mime: string) {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export function sentimentClass(sentiment: DeltaSentiment): string {
  switch (sentiment) {
    case "improved":
      return "text-emerald-300"
    case "regressed":
      return "text-red-300"
    case "neutral":
      return "text-amber-200/90"
    default:
      return "text-muted-foreground"
  }
}

export function timelinePoints(
  campaigns: CampaignIndexEntry[],
  bundles: Record<string, CampaignBundle | undefined>,
): Array<{
  campaign_id: string
  label: string
  version: string
  timestamp_utc: string
  latency: number | null
  cost: number | null
  co2e: number | null
  throughput: number | null
}> {
  const chrono = [...campaigns].sort((a, b) => {
    const ta = Date.parse(a.timestamp_utc || "") || 0
    const tb = Date.parse(b.timestamp_utc || "") || 0
    return ta - tb
  })
  return chrono.map((c) => {
    const bundle = bundles[c.campaign_id]
    const agg = bundle ? aggregateCampaign(bundle) : null
    return {
      campaign_id: c.campaign_id,
      label: c.label || c.campaign_id,
      version: c.benchmark_version,
      timestamp_utc: c.timestamp_utc,
      latency: agg?.avg_latency_ms ?? null,
      cost: agg?.total_api_cost_usd ?? null,
      co2e: agg?.avg_estimated_co2e_g ?? null,
      throughput: agg?.avg_tokens_per_sec ?? null,
    }
  })
}
