"use client"

import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

export function BenchmarkAnalyticsSkeleton() {
  return (
    <div className="space-y-8" data-testid="benchmark-analytics-skeleton">
      <div className="space-y-3">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-9 w-72" />
        <Skeleton className="h-4 w-96 max-w-full" />
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <Card key={i} className="p-4 border-border/50 bg-card/40">
            <Skeleton className="h-3 w-20 mb-3" />
            <Skeleton className="h-7 w-24" />
          </Card>
        ))}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card className="p-6 border-border/50 bg-card/40 space-y-4">
          <Skeleton className="h-5 w-48" />
          <Skeleton className="h-64 w-full" />
        </Card>
        <Card className="p-6 border-border/50 bg-card/40 space-y-4">
          <Skeleton className="h-5 w-48" />
          <Skeleton className="h-64 w-full" />
        </Card>
      </div>
    </div>
  )
}
