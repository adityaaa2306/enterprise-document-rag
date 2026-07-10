"use client"

import { ROUTING_PREFERENCE_OPTIONS, type RoutingPreference } from "@/lib/routing"

interface AdvancedRoutingSettingsProps {
  value: RoutingPreference
  onChange: (value: RoutingPreference) => void
}

export function AdvancedRoutingSettings({ value, onChange }: AdvancedRoutingSettingsProps) {
  return (
    <details className="group rounded-lg border border-border/50 bg-card/30 open:bg-card/50">
      <summary className="cursor-pointer list-none px-5 py-4 text-sm font-medium text-muted-foreground hover:text-foreground flex items-center justify-between">
        <span>Advanced settings</span>
        <span className="text-xs opacity-70 group-open:hidden">Optional · power users</span>
        <span className="text-xs opacity-70 hidden group-open:inline">Optimization preferences only</span>
      </summary>
      <div className="px-5 pb-5 space-y-3 border-t border-border/40 pt-4">
        <p className="text-xs text-muted-foreground leading-relaxed">
          These preferences only adjust Intelligent Router utility weights. They never
          bypass capability floors, domain risk rules, quality validation, or safety.
        </p>
        <p className="text-sm font-medium">Routing preference</p>
        <div className="space-y-2">
          {ROUTING_PREFERENCE_OPTIONS.map((opt) => (
            <label
              key={opt.id}
              className={`flex gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                value === opt.id
                  ? "border-primary bg-primary/10"
                  : "border-border/40 hover:border-border"
              }`}
            >
              <input
                type="radio"
                name="routing_preference"
                className="mt-1"
                checked={value === opt.id}
                onChange={() => onChange(opt.id)}
              />
              <span>
                <span className="block text-sm font-medium">{opt.label}</span>
                <span className="block text-xs text-muted-foreground mt-0.5">{opt.description}</span>
              </span>
            </label>
          ))}
        </div>
      </div>
    </details>
  )
}
