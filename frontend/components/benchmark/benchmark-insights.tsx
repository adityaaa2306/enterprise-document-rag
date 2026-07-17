"use client"

import { Card } from "@/components/ui/card"
import type { CampaignBundle } from "@/lib/benchmark-types"
import { displayParticipantName, fmtNum, fmtUsd } from "@/lib/benchmark-campaigns"

type Props = { bundle: CampaignBundle }

export function BenchmarkInsights({ bundle }: Props) {
  const dash = bundle.dashboard
  const h = dash.highlights
  const t = dash.totals
  const models = dash.models || []
  const questions = t.questions ?? bundle.config.question_count ?? 0
  const runs =
    (dash.table?.per_model || []).reduce((acc, r) => acc + (r.n_runs || 0), 0) ||
    questions * models.length

  const fastest = displayParticipantName(h.fastest_model?.model) || "—"
  const cheapest = displayParticipantName(h.lowest_estimated_cost?.model) || "—"
  const greenest = displayParticipantName(h.lowest_estimated_co2e?.model) || "—"
  const fastestTput = displayParticipantName(h.highest_tokens_per_sec?.model) || "—"
  const bestQuality =
    displayParticipantName(h.best_quality_model?.model) ||
    displayParticipantName(dash.quality?.best_quality_model?.model) ||
    "—"
  const qualityInsights = dash.quality?.insights || []
  const avgQuality = dash.quality?.avg_quality_score ?? t.avg_quality_score

  const sameCheapGreen = cheapest === greenest && cheapest !== "—"

  return (
    <Card className="p-6 md:p-7 bg-gradient-to-br from-card to-card/40 border-border/50">
      <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-emerald-400/90 mb-2">
        Benchmark insights
      </p>
      <h3 className="text-lg font-semibold tracking-tight mb-3">
        What this campaign tells you
      </h3>
      <div className="space-y-3 text-sm text-muted-foreground leading-relaxed max-w-4xl">
        <p>
          This campaign evaluated{" "}
          <span className="text-foreground font-medium">
            {models.length} participants
          </span>{" "}
          (GPT models and/or the Intelligent Router) on{" "}
          <span className="text-foreground font-medium">{questions} frozen questions</span>{" "}
          ({runs} total runs) in{" "}
          <span className="text-foreground font-medium">
            {fmtNum(t.total_runtime_sec, 1)} seconds
          </span>
          , spending an estimated{" "}
          <span className="text-foreground font-medium">
            {fmtUsd(t.total_api_cost_usd, 4)}
          </span>
          . Every participant answered from identical retrieved context — differences
          reflect generation/routing behavior, not retrieval variance.
        </p>
        <p>
          <span className="text-emerald-300 font-medium">{fastest}</span> delivered the
          lowest average latency
          {h.fastest_model
            ? ` (${fmtNum(h.fastest_model.value, 0)} ms)`
            : ""}
          .{" "}
          <span className="text-emerald-300 font-medium">{cheapest}</span> had the lowest
          estimated API cost
          {h.lowest_estimated_cost
            ? ` (${fmtUsd(h.lowest_estimated_cost.value, 5)} total)`
            : ""}
          {sameCheapGreen ? (
            <>
              {" "}
              and also the lowest estimated CO₂e
              {h.lowest_estimated_co2e
                ? ` (${fmtNum(h.lowest_estimated_co2e.value, 3)} g/query)`
                : ""}
              .
            </>
          ) : (
            <>
              . <span className="text-emerald-300 font-medium">{greenest}</span> produced
              the lowest estimated CO₂e
              {h.lowest_estimated_co2e
                ? ` (${fmtNum(h.lowest_estimated_co2e.value, 3)} g/query)`
                : ""}
              .
            </>
          )}{" "}
          Highest throughput went to{" "}
          <span className="text-emerald-300 font-medium">{fastestTput}</span>
          {h.highest_tokens_per_sec
            ? ` (${fmtNum(h.highest_tokens_per_sec.value, 1)} tok/s)`
            : ""}
          .
        </p>
        {avgQuality != null || bestQuality !== "—" ? (
          <p>
            Average answer quality
            {avgQuality != null ? (
              <>
                {" "}
                was{" "}
                <span className="text-foreground font-medium">
                  {fmtNum(avgQuality, 1)}/100
                </span>
              </>
            ) : null}
            {bestQuality !== "—" ? (
              <>
                {avgQuality != null ? ", with " : ". "}
                <span className="text-emerald-300 font-medium">{bestQuality}</span>{" "}
                leading on quality
                {h.best_quality_model || dash.quality?.best_quality_model
                  ? ` (${fmtNum(
                      (h.best_quality_model || dash.quality?.best_quality_model)
                        ?.value,
                      1,
                    )}/100)`
                  : ""}
                .
              </>
            ) : (
              "."
            )}
          </p>
        ) : null}
        {qualityInsights.length > 0 ? (
          <ul className="space-y-1.5 list-disc pl-5">
            {qualityInsights.map((line) => (
              <li key={line} className="text-muted-foreground">
                <span className="text-foreground/90">{line}</span>
              </li>
            ))}
          </ul>
        ) : null}
        <p>
          Token volume across the campaign:{" "}
          <span className="text-foreground font-medium">
            {fmtNum(t.total_prompt_tokens, 0)} prompt
          </span>
          {" · "}
          <span className="text-foreground font-medium">
            {fmtNum(t.total_completion_tokens, 0)} completion
          </span>
          {" · "}
          <span className="text-foreground font-medium">
            {fmtNum(t.total_tokens, 0)} total
          </span>
          . Use the trade-off and quality charts to weigh speed, cost, carbon, and
          answer quality when choosing a default generation path for this workload.
        </p>
      </div>
    </Card>
  )
}
