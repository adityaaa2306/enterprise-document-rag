"use client"

import { motion } from "framer-motion"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Sparkles, Brain, ShieldCheck } from "lucide-react"
import { AdvancedRoutingSettings } from "@/components/advanced-routing-settings"
import type { RoutingPreference } from "@/lib/routing"

interface SmartRoutingPanelProps {
  fileName: string
  preference: RoutingPreference
  onPreferenceChange: (p: RoutingPreference) => void
  onSubmit: () => void
  onBack: () => void
  isSubmitting?: boolean
}

export function SmartRoutingPanel({
  fileName,
  preference,
  onPreferenceChange,
  onSubmit,
  onBack,
  isSubmitting = false,
}: SmartRoutingPanelProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="space-y-6 max-w-3xl"
    >
      <Card className="p-4 bg-primary/10 border-primary/30">
        <p className="text-sm text-foreground">
          Selected: <span className="font-semibold">{fileName}</span>
        </p>
        <button
          type="button"
          onClick={onBack}
          className="text-xs text-primary hover:underline mt-1"
        >
          Change file
        </button>
      </Card>

      <Card className="p-6 bg-card/50 border-border/50 space-y-4">
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-lg bg-primary/20 flex items-center justify-center shrink-0">
            <Sparkles className="w-5 h-5 text-primary" />
          </div>
          <div>
            <h2 className="text-xl font-semibold flex items-center gap-2">
              Smart Routing
              <span className="text-xs font-medium px-2 py-0.5 rounded bg-primary/20 text-primary">
                Default
              </span>
            </h2>
            <p className="text-sm text-muted-foreground mt-2 leading-relaxed">
              The platform automatically selects the most suitable AI models based on
              document understanding, reasoning requirements, retrieval confidence,
              runtime availability, latency, cost, and carbon footprint.
            </p>
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2">
          <div className="flex gap-2 text-sm text-muted-foreground">
            <Brain className="w-4 h-4 text-primary shrink-0 mt-0.5" />
            <span>CRE computes capability requirements from document features.</span>
          </div>
          <div className="flex gap-2 text-sm text-muted-foreground">
            <ShieldCheck className="w-4 h-4 text-primary shrink-0 mt-0.5" />
            <span>Domain floors and quality validation are never overridden.</span>
          </div>
        </div>
      </Card>

      <AdvancedRoutingSettings value={preference} onChange={onPreferenceChange} />

      <Button
        size="lg"
        className="w-full"
        onClick={onSubmit}
        disabled={isSubmitting}
      >
        {isSubmitting ? "Starting…" : "Process document"}
      </Button>
    </motion.div>
  )
}
