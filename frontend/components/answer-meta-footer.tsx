"use client"

import { cn } from "@/lib/utils"

export type AnswerMetaFooterProps = {
  modelUsed?: string | null
  confidence?: number | null
  latencyMs?: number | null
  documentsRetrieved?: number | null
  carbonSavedGrams?: number | null
  className?: string
}

function friendlyModelName(model?: string | null): string | null {
  if (!model) return null
  const leaf = model.includes("/") ? model.split("/").pop()! : model
  return leaf
    .replace(/-instruct.*$/i, "")
    .replace(/-it$/i, "")
    .replace(/-/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .trim()
}

function MetaCell({
  label,
  value,
}: {
  label: string
  value: string
}) {
  return (
    <div className="min-w-[7rem] space-y-1">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className="text-sm font-medium text-foreground leading-snug">{value}</p>
    </div>
  )
}

export function AnswerMetaFooter({
  modelUsed,
  confidence,
  latencyMs,
  documentsRetrieved,
  carbonSavedGrams,
  className,
}: AnswerMetaFooterProps) {
  const model = friendlyModelName(modelUsed)
  const hasAnything =
    model ||
    confidence != null ||
    latencyMs != null ||
    documentsRetrieved != null ||
    carbonSavedGrams != null

  if (!hasAnything) return null

  return (
    <div
      className={cn(
        "mt-4 rounded-xl border border-border/50 bg-background/50 px-4 py-3",
        className,
      )}
    >
      <div className="flex flex-wrap gap-x-8 gap-y-3">
        {model ? <MetaCell label="Model" value={model} /> : null}
        {confidence != null ? (
          <MetaCell
            label="Confidence"
            value={`${Math.round(confidence * 100)}%`}
          />
        ) : null}
        {latencyMs != null ? (
          <MetaCell
            label="Processing Time"
            value={`${(latencyMs / 1000).toFixed(1)} seconds`}
          />
        ) : null}
        {documentsRetrieved != null ? (
          <MetaCell
            label="Documents Retrieved"
            value={String(documentsRetrieved)}
          />
        ) : null}
        {carbonSavedGrams != null ? (
          <MetaCell
            label="Carbon Saved"
            value={`${carbonSavedGrams.toFixed(4)}g CO2e`}
          />
        ) : null}
      </div>
    </div>
  )
}
