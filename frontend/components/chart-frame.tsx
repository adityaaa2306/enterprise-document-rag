"use client"

import type { ComponentProps } from "react"
import { ResponsiveContainer } from "recharts"
import { cn } from "@/lib/utils"

type Props = {
  /** Fixed pixel height — avoids Recharts 3 first-paint width/height(-1) warnings. */
  height: number
  children: ComponentProps<typeof ResponsiveContainer>["children"]
  className?: string
}

/**
 * Sized wrapper for Recharts. Percentage height + percentage width reports -1
 * on the first paint (before ResizeObserver), which spams the console.
 */
export function ChartFrame({ height, children, className }: Props) {
  return (
    <div className={cn("w-full min-w-0", className)} style={{ height }}>
      <ResponsiveContainer width="100%" height={height} minWidth={0}>
        {children}
      </ResponsiveContainer>
    </div>
  )
}
