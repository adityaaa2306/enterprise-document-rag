"use client"

import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

export function ResultsPanelSkeleton() {
  return (
    <div className="space-y-4" data-testid="results-panel-skeleton">
      <Card className="p-6 bg-card/50 border-border/50 space-y-4">
        <Skeleton className="h-6 w-48" />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
        <Skeleton className="h-48 w-full" />
      </Card>
    </div>
  )
}

export function SummarySkeleton() {
  return (
    <Card className="p-6 bg-card/50 border-border/50 space-y-3" data-testid="summary-skeleton">
      <Skeleton className="h-5 w-40" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-5/6" />
      <Skeleton className="h-4 w-4/6" />
      <Skeleton className="h-32 w-full mt-4" />
    </Card>
  )
}

export function ChatSkeleton() {
  return (
    <Card className="p-6 bg-card/50 border-border/50 space-y-4" data-testid="chat-skeleton">
      <Skeleton className="h-5 w-36" />
      <div className="space-y-3">
        <Skeleton className="h-16 w-3/4" />
        <Skeleton className="h-16 w-2/3 ml-auto" />
        <Skeleton className="h-16 w-3/4" />
      </div>
      <Skeleton className="h-10 w-full" />
    </Card>
  )
}

export function DashboardChartsSkeleton() {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6" data-testid="dashboard-charts-skeleton">
      <Card className="p-6 bg-card/50 border-border/50 space-y-4">
        <Skeleton className="h-5 w-52" />
        <Skeleton className="h-64 w-full" />
      </Card>
      <Card className="p-6 bg-card/50 border-border/50 space-y-4">
        <Skeleton className="h-5 w-52" />
        <Skeleton className="h-64 w-full" />
      </Card>
    </div>
  )
}
