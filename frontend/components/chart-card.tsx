"use client"

import { motion } from "framer-motion"
import { Card } from "@/components/ui/card"
import type { ReactNode } from "react"

interface ChartCardProps {
  title: string
  children: ReactNode
  delay?: number
}

export function ChartCard({ title, children, delay = 0 }: ChartCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.5 }}
      whileHover={{ y: -4 }}
    >
      <Card className="p-6 bg-gradient-to-br from-card to-card/50 border-border/50 hover:border-primary/30 transition-colors">
        <h3 className="text-lg font-semibold mb-4">{title}</h3>
        <div className="w-full overflow-auto">{children}</div>
      </Card>
    </motion.div>
  )
}
