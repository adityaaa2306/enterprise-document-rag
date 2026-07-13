"use client"

import { FileText } from "lucide-react"
import { cn } from "@/lib/utils"

export type RetrievedChunkMeta = {
  id?: string
  score?: number
  parent_section?: string | null
  citation?: number | null
  preview?: string | null
  rank?: number | null
}

export type AnswerSourceItem = {
  title: string
  snippet: string
  pageLabel?: string | null
  confidenceLabel?: string | null
  citation?: number | null
}

function confidenceFromScore(score?: number | null): string | null {
  if (score == null || Number.isNaN(score)) return null
  // Scores are normalized relevance (0–1) from the API after explainability mapping.
  if (score >= 0.75) return "High"
  if (score >= 0.45) return "Medium"
  return "Low"
}

function titleFromSection(
  section?: string | null,
  preview?: string | null,
  index?: number,
): string {
  const cleaned = (section || "").trim()
  if (cleaned && !/^\(?preamble\)?$/i.test(cleaned)) {
    const leaf = cleaned.split(/[>/|]/).filter(Boolean).pop()?.trim()
    return leaf || cleaned
  }
  const fromPreview = (preview || "")
    .trim()
    .split(/\n/)
    .map((l) => l.trim())
    .find((l) => l.length >= 8)
  if (fromPreview) {
    return fromPreview.length > 90 ? `${fromPreview.slice(0, 87)}…` : fromPreview
  }
  return `Source ${typeof index === "number" ? index + 1 : ""}`.trim()
}

function snippetText(preview?: string | null, fallback?: string | null): string {
  const raw = (preview || fallback || "").trim().replace(/\s+/g, " ")
  if (!raw) return "No preview available."
  return raw.length > 220 ? `${raw.slice(0, 217)}…` : raw
}

/**
 * Prefer passage-aligned retrieved_chunks (one row per citation).
 * Fall back to legacy sources[] when chunks are absent.
 */
export function buildAnswerSources(
  sources?: string[] | null,
  retrievedChunks?: RetrievedChunkMeta[] | null,
  limit = 6,
): AnswerSourceItem[] {
  const texts = (sources || []).filter((s) => typeof s === "string" && s.trim())
  const chunks = retrievedChunks || []
  const items: AnswerSourceItem[] = []
  const seenCitations = new Set<number>()

  if (chunks.length > 0) {
    for (let i = 0; i < Math.min(limit, chunks.length); i++) {
      const chunk = chunks[i]
      const citation = chunk?.citation ?? i + 1
      if (seenCitations.has(citation)) continue
      seenCitations.add(citation)

      // Prefer chunk.preview; only use sources[i] when arrays are aligned 1:1
      const alignedText =
        texts.length === chunks.length
          ? texts[i]
          : texts.length === 1 && i === 0
            ? texts[0]
            : ""
      const preview = chunk?.preview || alignedText

      items.push({
        title: titleFromSection(chunk?.parent_section, preview, i),
        snippet: snippetText(preview, alignedText),
        pageLabel: chunk?.parent_section
          ? `Section: ${chunk.parent_section}`
          : chunk?.id
            ? `Chunk: ${String(chunk.id).slice(0, 12)}`
            : null,
        confidenceLabel: confidenceFromScore(chunk?.score),
        citation,
      })
    }
    return items
  }

  for (let i = 0; i < Math.min(limit, texts.length); i++) {
    items.push({
      title: titleFromSection(null, texts[i], i),
      snippet: snippetText(texts[i]),
      pageLabel: null,
      confidenceLabel: null,
      citation: i + 1,
    })
  }
  return items
}

type AnswerSourcesProps = {
  sources?: string[] | null
  retrievedChunks?: RetrievedChunkMeta[] | null
  className?: string
}

export function AnswerSources({
  sources,
  retrievedChunks,
  className,
}: AnswerSourcesProps) {
  const items = buildAnswerSources(sources, retrievedChunks)
  if (items.length === 0) return null

  return (
    <section className={cn("mt-4 space-y-3", className)}>
      <h4 className="text-sm font-semibold tracking-tight text-foreground">
        Sources
      </h4>
      <ol className="space-y-3">
        {items.map((item, index) => (
          <li
            key={`${item.citation ?? index}-${item.title}-${index}`}
            className="rounded-lg border border-border/50 bg-background/40 p-3"
          >
            <div className="flex items-start gap-2.5">
              <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-primary/15 text-xs font-semibold text-primary">
                {item.citation ?? index + 1}
              </div>
              <div className="min-w-0 flex-1 space-y-1.5">
                <p className="text-sm font-medium text-foreground leading-snug">
                  {item.title}
                </p>
                <p className="text-xs leading-relaxed text-muted-foreground">
                  {item.snippet}
                </p>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground/90">
                  {item.pageLabel ? (
                    <span className="inline-flex items-center gap-1">
                      <FileText className="h-3 w-3" />
                      {item.pageLabel}
                    </span>
                  ) : null}
                  {item.confidenceLabel ? (
                    <span>Relevance: {item.confidenceLabel}</span>
                  ) : null}
                </div>
              </div>
            </div>
          </li>
        ))}
      </ol>
    </section>
  )
}
