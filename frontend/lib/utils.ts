import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Models sometimes wrap the whole answer in ```markdown ... ```.
 * That makes ReactMarkdown render one giant code block — unwrap it.
 */
export function unwrapOuterMarkdownFence(text: string): string {
  const trimmed = (text || "").trim()
  if (!trimmed.startsWith("```")) return text

  const match = trimmed.match(
    /^```(?:markdown|md|gfm)?\s*\r?\n([\s\S]*?)\r?\n```\s*$/i,
  )
  if (match) return match[1].replace(/\s+$/, "")

  // Closing fence may sit on the same line as the last content
  const loose = trimmed.match(
    /^```(?:markdown|md|gfm)?\s*\r?\n([\s\S]*?)```\s*$/i,
  )
  if (loose) return loose[1].replace(/\s+$/, "")

  return text
}
