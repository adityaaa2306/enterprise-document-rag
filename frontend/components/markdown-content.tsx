"use client"

import { useMemo } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import rehypeSanitize, { defaultSchema } from "rehype-sanitize"
import rehypeHighlight from "rehype-highlight"
import { cn, unwrapOuterMarkdownFence } from "@/lib/utils"

import "highlight.js/styles/github-dark.css"

const sanitizeSchema = {
  ...defaultSchema,
  attributes: {
    ...defaultSchema.attributes,
    code: [...(defaultSchema.attributes?.code || []), ["className"]],
    span: [...(defaultSchema.attributes?.span || []), ["className"]],
    pre: [...(defaultSchema.attributes?.pre || []), ["className"]],
    a: [
      ...(defaultSchema.attributes?.a || []),
      ["target"],
      ["rel"],
      ["className"],
    ],
  },
}

type MarkdownContentProps = {
  content: string
  className?: string
  /** Soften heading scale for chat bubbles */
  compact?: boolean
}

/**
 * Safe GitHub-Flavored Markdown renderer.
 * Sanitizes HTML and supports progressive/partial Markdown without flickering.
 */
export function MarkdownContent({
  content,
  className,
  compact = false,
}: MarkdownContentProps) {
  const plugins = useMemo(
    () => ({
      remark: [remarkGfm],
      rehype: [rehypeHighlight, [rehypeSanitize, sanitizeSchema] as const],
    }),
    [],
  )

  const normalized = useMemo(
    () => unwrapOuterMarkdownFence(content || ""),
    [content],
  )

  if (!normalized?.trim()) {
    return null
  }

  return (
    <div
      className={cn(
        "markdown-body max-w-none text-foreground",
        compact ? "markdown-body--compact" : "markdown-body--comfortable",
        className,
      )}
    >
      <ReactMarkdown
        remarkPlugins={plugins.remark}
        rehypePlugins={plugins.rehype as any}
        components={{
          a: ({ href, children, ...props }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              {...props}
            >
              {children}
            </a>
          ),
          table: ({ children, ...props }) => (
            <div className="markdown-table-wrap">
              <table {...props}>{children}</table>
            </div>
          ),
        }}
      >
        {normalized}
      </ReactMarkdown>
    </div>
  )
}
