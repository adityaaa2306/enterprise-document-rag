"use client"

import { useState } from "react"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Slider } from "@/components/ui/slider"
import { Label } from "@/components/ui/label"
import { ArrowLeft, Play, Pause, RotateCcw } from "lucide-react"
import { useRouter } from "next/navigation"

export default function SimulationPage() {
  const router = useRouter()
  const [isRunning, setIsRunning] = useState(false)
  const [progress, setProgress] = useState(0)
  const [parameters, setParameters] = useState({
    documentCount: 500,
    complexity: 50,
    accuracy: 95,
    speed: 75,
  })

  const handleSimulationStart = () => {
    setIsRunning(true)
    let currentProgress = 0
    const interval = setInterval(() => {
      currentProgress += Math.random() * 5
      if (currentProgress >= 100) {
        setProgress(100)
        setIsRunning(false)
        clearInterval(interval)
      } else {
        setProgress(currentProgress)
      }
    }, 100)
  }

  const handleSimulationReset = () => {
    setProgress(0)
    setIsRunning(false)
  }

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <div className="border-b border-border bg-background/50 backdrop-blur sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button
              onClick={() => router.back()}
              className="flex items-center gap-2 text-muted-foreground hover:text-foreground transition-colors"
            >
              <ArrowLeft className="w-4 h-4" />
              Back
            </button>
            <h1 className="text-2xl font-bold">Simulation Sandbox</h1>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="max-w-4xl mx-auto px-6 py-12">
        {/* Parameter Controls */}
        <Card className="p-8 border-border mb-8">
          <p className="text-sm text-muted-foreground mb-6">
            Demo sandbox for exploring parameter tradeoffs. This is not the live CRE / Intelligent Router used by Process document.
          </p>
          <h2 className="text-xl font-semibold mb-6">Simulation Parameters</h2>
          <div className="space-y-6">
            <div>
              <div className="flex justify-between mb-3">
                <Label>Document Count</Label>
                <span className="font-semibold">{parameters.documentCount}</span>
              </div>
              <Slider
                value={[parameters.documentCount]}
                onValueChange={(value) => setParameters({ ...parameters, documentCount: value[0] })}
                min={100}
                max={10000}
                step={100}
                disabled={isRunning}
                className="w-full"
              />
            </div>

            <div>
              <div className="flex justify-between mb-3">
                <Label>Complexity Level</Label>
                <span className="font-semibold">{parameters.complexity}%</span>
              </div>
              <Slider
                value={[parameters.complexity]}
                onValueChange={(value) => setParameters({ ...parameters, complexity: value[0] })}
                min={0}
                max={100}
                step={5}
                disabled={isRunning}
                className="w-full"
              />
            </div>

            <div>
              <div className="flex justify-between mb-3">
                <Label>Target Accuracy</Label>
                <span className="font-semibold">{parameters.accuracy}%</span>
              </div>
              <Slider
                value={[parameters.accuracy]}
                onValueChange={(value) => setParameters({ ...parameters, accuracy: value[0] })}
                min={70}
                max={99}
                step={1}
                disabled={isRunning}
                className="w-full"
              />
            </div>

            <div>
              <div className="flex justify-between mb-3">
                <Label>Processing Speed</Label>
                <span className="font-semibold">{parameters.speed}%</span>
              </div>
              <Slider
                value={[parameters.speed]}
                onValueChange={(value) => setParameters({ ...parameters, speed: value[0] })}
                min={25}
                max={100}
                step={5}
                disabled={isRunning}
                className="w-full"
              />
            </div>
          </div>
        </Card>

        {/* Simulation Status */}
        <Card className="p-8 border-border mb-8">
          <h2 className="text-xl font-semibold mb-6">Simulation Status</h2>
          <div className="space-y-6">
            <div>
              <div className="flex justify-between mb-2">
                <span className="text-muted-foreground">Progress</span>
                <span className="font-semibold">{Math.round(progress)}%</span>
              </div>
              <div className="w-full bg-input rounded-full h-3">
                <div
                  className="bg-primary rounded-full h-3 transition-all duration-100"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="p-4 bg-input rounded-lg">
                <p className="text-sm text-muted-foreground mb-1">Estimated Time</p>
                <p className="text-2xl font-bold">
                  {Math.round(((100 - progress) * (100 - parameters.speed)) / 1000)}m
                </p>
              </div>
              <div className="p-4 bg-input rounded-lg">
                <p className="text-sm text-muted-foreground mb-1">Est. Cost</p>
                <p className="text-2xl font-bold">${(parameters.documentCount * 0.08).toFixed(2)}</p>
              </div>
            </div>
          </div>
        </Card>

        {/* Controls */}
        <div className="flex gap-4 justify-end">
          <Button variant="outline" onClick={handleSimulationReset} disabled={isRunning}>
            <RotateCcw className="w-4 h-4 mr-2" />
            Reset
          </Button>
          <Button
            onClick={isRunning ? () => setIsRunning(false) : handleSimulationStart}
            className="bg-primary hover:bg-primary/90"
          >
            {isRunning ? (
              <>
                <Pause className="w-4 h-4 mr-2" />
                Pause
              </>
            ) : (
              <>
                <Play className="w-4 h-4 mr-2" />
                Start Simulation
              </>
            )}
          </Button>
        </div>
      </div>
    </div>
  )
}
