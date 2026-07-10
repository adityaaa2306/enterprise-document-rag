"use client"

import { motion } from "framer-motion"
import { Card } from "@/components/ui/card"
import type { LucideIcon } from "lucide-react"

interface KPICardProps {
  title: string
  value: string | number
  unit?: string
  icon: LucideIcon
  trend?: {
    value: number
    direction: "up" | "down"
  }
  delay?: number
}

export function KPICard({ title, value, unit, icon: Icon, trend, delay = 0 }: KPICardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.5 }}
      whileHover={{ y: -4 }}
    >
      <Card className="p-6 bg-gradient-to-br from-card to-card/50 border-border/50 hover:border-primary/30 transition-colors">
        <div className="flex items-start justify-between mb-4">
          <div>
            <p className="text-sm text-muted-foreground mb-2">{title}</p>
            <div className="flex items-baseline gap-2">
              <p className="text-3xl font-bold text-foreground">{value}</p>
              {unit && <span className="text-sm text-muted-foreground">{unit}</span>}
            </div>
          </div>
          <div className="w-10 h-10 rounded-lg bg-primary/20 flex items-center justify-center">
            <Icon className="w-5 h-5 text-primary" />
          </div>
        </div>

        {trend && (
          <div className={`text-xs font-medium ${trend.direction === "up" ? "text-green-400" : "text-red-400"}`}>
            {trend.direction === "up" ? "↑" : "↓"} {trend.value}% from last week
          </div>
        )}
      </Card>
    </motion.div>
  )
}
