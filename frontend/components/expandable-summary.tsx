"use client"

import { useState } from "react"
import { ChevronDown, ChevronUp, Copy, Download } from "lucide-react"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { MarkdownContent } from "@/components/markdown-content"
import { cn } from "@/lib/utils"

type Props = {
  content: string
  onCopy?: () => void
  onDownload?: () => void
  collapsedMaxPx?: number
}

/**
 * Fixed-height summary with gradient fade + expand/collapse.
 */
export function ExpandableSummary({
  content,
  onCopy,
  onDownload,
  collapsedMaxPx = 220,
}: Props) {
  const [expanded, setExpanded] = useState(false)

  return (
    <Card className="bg-card/50 border-border/50 overflow-hidden">
      <div className="flex gap-3 px-6 pt-5 pb-2">
        {onCopy ? (
          <Button
            size="sm"
            variant="outline"
            className="gap-2 bg-transparent"
            onClick={(e) => {
              e.stopPropagation()
              onCopy()
            }}
          >
            <Copy className="w-4 h-4" />
            Copy
          </Button>
        ) : null}
        {onDownload ? (
          <Button
            size="sm"
            variant="outline"
            className="gap-2 bg-transparent"
            onClick={(e) => {
              e.stopPropagation()
              onDownload()
            }}
          >
            <Download className="w-4 h-4" />
            Download
          </Button>
        ) : null}
      </div>

      <button
        type="button"
        className="relative w-full text-left cursor-pointer group"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        <div
          className={cn(
            "px-6 transition-[max-height] duration-[350ms] ease-in-out",
            expanded ? "max-h-[4000px]" : "overflow-hidden",
          )}
          style={expanded ? undefined : { maxHeight: collapsedMaxPx }}
        >
          <div className="mx-auto w-full max-w-3xl pb-12">
            <MarkdownContent content={content} />
          </div>
        </div>

        {!expanded ? (
          <div
            className="pointer-events-none absolute inset-x-0 bottom-0 h-20 bg-gradient-to-t from-card via-card/90 to-transparent"
            aria-hidden
          />
        ) : null}

        <div className="absolute inset-x-0 bottom-0 flex justify-center pb-2.5 pt-1">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-border/50 bg-card/95 px-3 py-1 text-xs text-muted-foreground shadow-sm group-hover:text-foreground group-hover:border-border transition-colors">
            {expanded ? (
              <>
                <ChevronUp className="w-3.5 h-3.5" />
                Show less
              </>
            ) : (
              <>
                <ChevronDown className="w-3.5 h-3.5" />
                Show more
              </>
            )}
          </span>
        </div>
      </button>
    </Card>
  )
}
