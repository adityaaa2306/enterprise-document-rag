/**
 * Client-side strip of carbon/dashboard metrics that sometimes leak into
 * the LLM document summary markdown. Prefer this over re-prompting.
 */

const SECTION_HEADINGS = [
  "carbon",
  "emissions",
  "co2",
  "co₂",
  "operational emissions",
  "model comparison",
  "frontier comparison",
  "grid intensity",
  "energy → pue",
  "energy -> pue",
  "carbon accounting",
  "carbon report",
  "job report",
  "baseline vs",
  "reduction %",
]

function isMetricHeading(line: string): boolean {
  const t = line.replace(/^#{1,6}\s*/, "").trim().toLowerCase()
  return SECTION_HEADINGS.some((h) => t.includes(h))
}

function looksLikeMetricTableRow(line: string): boolean {
  const lower = line.toLowerCase()
  if (!line.includes("|")) return false
  return (
    /gco2|co₂|co2e|reduction|baseline|optimized|grid intensity|kwh|pue/.test(lower) ||
    /estimated\s+g/.test(lower)
  )
}

/**
 * Remove carbon/metrics sections and tables from summary markdown.
 * Leaves document content / key findings intact.
 */
export function stripSummaryMetrics(markdown: string): string {
  if (!markdown) return ""
  const lines = markdown.replace(/\r\n/g, "\n").split("\n")
  const out: string[] = []
  let skipSection = false
  let inMetricTable = false

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const trimmed = line.trim()

    if (/^#{1,6}\s/.test(trimmed)) {
      if (isMetricHeading(trimmed)) {
        skipSection = true
        inMetricTable = false
        continue
      }
      skipSection = false
      inMetricTable = false
      out.push(line)
      continue
    }

    if (skipSection) {
      // Stop skipping when we hit a non-metric heading (handled above) or blank + prose
      // Keep skipping until next heading.
      continue
    }

    // Standalone metric tables (GFM)
    if (trimmed.startsWith("|") && looksLikeMetricTableRow(trimmed)) {
      inMetricTable = true
      continue
    }
    if (inMetricTable) {
      if (trimmed.startsWith("|") || /^\|?[\s:-]+\|/.test(trimmed)) continue
      inMetricTable = false
    }

    // Drop legacy boilerplate paragraphs
    if (/chatgpt-class|chunk count\s*×|4\.32\s*g|energy\s*→\s*pue\s*→\s*grid/i.test(trimmed)) {
      continue
    }
    if (/^co₂e\s*\(g\)\s*=|^co2e\s*\(g\)\s*=/i.test(trimmed)) {
      continue
    }

    out.push(line)
  }

  return out
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim()
}
