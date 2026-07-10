"use client"

import { motion } from "framer-motion"
import { Card } from "@/components/ui/card"
import { AlertCircle, CheckCircle2, Clock } from "lucide-react"

interface LogEntry {
  id: string
  timestamp: string
  message: string
  type: "info" | "warning" | "success"
}

interface LiveFeedProps {
  logs: LogEntry[]
}

export function LiveFeed({ logs }: LiveFeedProps) {
  const getIcon = (type: string) => {
    switch (type) {
      case "success":
        return <CheckCircle2 className="w-4 h-4 text-green-400" />
      case "warning":
        return <AlertCircle className="w-4 h-4 text-amber-400" />
      default:
        return <Clock className="w-4 h-4 text-blue-400" />
    }
  }

  return (
    <Card className="p-6 bg-card/50 border-border/50">
      <h3 className="text-lg font-semibold mb-4">Live Job Status</h3>
      <div className="space-y-3 max-h-96 overflow-y-auto">
        <motion.div layout>
          {logs.map((log, index) => (
            <motion.div
              key={log.id}
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: index * 0.05 }}
              className="flex items-start gap-3 p-3 rounded-lg bg-background/50 border border-border/30"
            >
              <div className="mt-1 flex-shrink-0">{getIcon(log.type)}</div>
              <div className="flex-1 min-w-0">
                <p className="text-sm text-foreground">{log.message}</p>
                <p className="text-xs text-muted-foreground mt-1">{log.timestamp}</p>
              </div>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </Card>
  )
}
