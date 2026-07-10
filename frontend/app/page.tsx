"use client"

import { useRouter } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { ArrowRight, Zap, BarChart3, Settings } from "lucide-react"

export default function Home() {
  const router = useRouter()

  return (
    <div className="min-h-screen bg-gradient-to-br from-background via-background to-background">
      {/* Navigation */}
      <nav className="border-b border-border bg-background/50 backdrop-blur">
        <div className="max-w-7xl mx-auto px-6 py-4 flex justify-between items-center">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
              <Zap className="w-5 h-5 text-primary-foreground" />
            </div>
            <h1 className="text-xl font-bold">Sustainability Manager</h1>
          </div>
          <div className="flex gap-3">
            <Button variant="outline" onClick={() => router.push("/dashboard")}>
              Dashboard
            </Button>
            <Button variant="outline" onClick={() => router.push("/login")}>
              Login
            </Button>
            <Button onClick={() => router.push("/new-job")}>New Job</Button>
          </div>
        </div>
      </nav>

      {/* Hero Section */}
      <div className="max-w-7xl mx-auto px-6 py-24">
        <div className="text-center mb-16">
          <h2 className="text-5xl font-bold mb-4 text-balance">Intelligent Document Processing</h2>
          <p className="text-xl text-muted-foreground mb-8 max-w-2xl mx-auto">
            Upload a document and Smart Routing selects the right models automatically — capability-first,
            with carbon, cost, and latency as outcomes you can inspect afterward.
          </p>
          <div className="flex gap-4 justify-center">
            <Button size="lg" onClick={() => router.push("/new-job")}>
              Create New Job <ArrowRight className="w-4 h-4 ml-2" />
            </Button>
            <Button size="lg" variant="outline" onClick={() => router.push("/dashboard")}>
              View Dashboard
            </Button>
          </div>
        </div>

        {/* Feature Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <Card className="p-8 bg-card/50 border-border hover:border-primary/50 transition-colors">
            <div className="w-12 h-12 rounded-lg bg-primary/20 flex items-center justify-center mb-4">
              <Zap className="w-6 h-6 text-primary" />
            </div>
            <h3 className="text-lg font-semibold mb-2">Smart Routing</h3>
            <p className="text-muted-foreground">
              CRE and the Intelligent Router choose models from document understanding — no Eco/Balanced/Quality picker
            </p>
          </Card>

          <Card className="p-8 bg-card/50 border-border hover:border-primary/50 transition-colors">
            <div className="w-12 h-12 rounded-lg bg-secondary/20 flex items-center justify-center mb-4">
              <BarChart3 className="w-6 h-6 text-secondary" />
            </div>
            <h3 className="text-lg font-semibold mb-2">Processing Insights</h3>
            <p className="text-muted-foreground">
              See why a model was selected, carbon outcomes, escalation, and retrieval strategy after each job
            </p>
          </Card>

          <Card className="p-8 bg-card/50 border-border hover:border-primary/50 transition-colors">
            <div className="w-12 h-12 rounded-lg bg-accent/20 flex items-center justify-center mb-4">
              <Settings className="w-6 h-6 text-accent" />
            </div>
            <h3 className="text-lg font-semibold mb-2">Optional Preferences</h3>
            <p className="text-muted-foreground">
              Advanced settings nudge latency, cost, or carbon weights — never below capability floors
            </p>
          </Card>
        </div>
      </div>
    </div>
  )
}
