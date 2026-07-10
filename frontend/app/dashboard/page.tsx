"use client"

import { motion } from "framer-motion"
import { Sidebar } from "@/components/sidebar"
import { TopBar } from "@/components/top-bar"
import { apiFetch } from "@/lib/api"
import { KPICard } from "@/components/kpi-card"
import { ChartCard } from "@/components/chart-card"
import { DocumentHistory } from "@/components/document-history"
import { useState, useEffect } from "react"
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts"
import { TrendingUp, Leaf, Star, Zap } from "lucide-react"

// Placeholder for Agent Usage (Real persistence for this not requested yet, keeping static or simple randomization)
const agentUsageData = [
  { name: "Light-Summarizer", usage: 450 },
  { name: "Medium-Summarizer", usage: 280 },
  { name: "Triage Agent", usage: 190 },
  { name: "Table-to-Text", usage: 120 },
  { name: "Other", usage: 60 },
]

interface DashboardStats {
  total_carbon_saved: number
  total_docs: number
  avg_efficiency: number
  carbon_trend: any[]
}

export default function Dashboard() {
  const [stats, setStats] = useState<DashboardStats>({
    total_carbon_saved: 0,
    total_docs: 0,
    avg_efficiency: 0,
    carbon_trend: []
  })

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const res = await apiFetch("/dashboard-stats")
        if (res.ok) {
          const data = await res.json()
          setStats(data)
        }
      } catch (e) {
        console.error("Failed to fetch dashboard stats", e)
      }
    }

    fetchStats()
    // Poll every 10 seconds
    const interval = setInterval(fetchStats, 10000)
    return () => clearInterval(interval)
  }, [])

  return (
    <div className="flex">
      <Sidebar />
      <div className="flex-1">
        <TopBar />
        <main className="p-8">
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <h1 className="text-3xl font-bold mb-2">Dashboard & Analytics</h1>
            <p className="text-muted-foreground mb-8">
              Carbon and efficiency KPIs reflect outcomes of Smart Routing — not a manual mode choice.
            </p>

            {/* KPI Cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
              <KPICard
                title="Total Carbon Saved"
                value={stats.total_carbon_saved.toFixed(4)}
                unit="g CO2e"
                icon={Leaf}
                trend={{ value: 24, direction: "up" }} // Trend comparison logic omitted for brevity
                delay={0}
              />
              <KPICard
                title="Documents Processed"
                value={stats.total_docs.toLocaleString()}
                icon={Zap}
                trend={{ value: 12, direction: "up" }}
                delay={0.1}
              />
              <KPICard
                title="Jobs via Smart Routing"
                value={stats.total_docs.toLocaleString()}
                icon={Star}
                trend={{ value: 0, direction: "neutral" }}
                delay={0.2}
              />
              <KPICard
                title="Energy Efficiency"
                value={stats.avg_efficiency.toFixed(0)}
                unit="%"
                icon={TrendingUp}
                trend={{ value: 10, direction: "up" }}
                delay={0.3}
              />
            </div>

            {/* Charts */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
              <ChartCard title="Daily Carbon Savings vs Baseline" delay={0.4}>
                <ResponsiveContainer width="100%" height={300}>
                  <LineChart data={stats.carbon_trend}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
                    <XAxis dataKey="date" stroke="rgba(255,255,255,0.5)" />
                    <YAxis stroke="rgba(255,255,255,0.5)" />
                    <Tooltip
                      contentStyle={{ background: "rgba(0,0,0,0.8)", border: "1px solid rgba(255,255,255,0.1)" }}
                    />
                    <Legend />
                    <Line type="monotone" dataKey="savings" name="Actual Savings" stroke="#22c55e" strokeWidth={2} dot={false} />
                    <Line
                      type="monotone"
                      dataKey="baseline"
                      name="Baseline (Standard)"
                      stroke="rgba(255,255,255,0.3)"
                      strokeWidth={2}
                      dot={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </ChartCard>

              <ChartCard title="Energy Efficiency Trends" delay={0.5}>
                {/* Re-using carbon trend data for efficiency to show correlation, or just show efficiency line */}
                <ResponsiveContainer width="100%" height={300}>
                  <LineChart data={stats.carbon_trend}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
                    <XAxis dataKey="date" stroke="rgba(255,255,255,0.5)" />
                    <YAxis stroke="rgba(255,255,255,0.5)" />
                    <Tooltip
                      contentStyle={{ background: "rgba(0,0,0,0.8)", border: "1px solid rgba(255,255,255,0.1)" }}
                    />
                    <Legend />
                    <Line type="monotone" dataKey="savings" name="Carbon Saved" stroke="#3b82f6" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </ChartCard>
            </div>

            {/* Agent Usage */}
            <ChartCard title="Worker Agent Utilization" delay={0.6}>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={agentUsageData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
                  <XAxis dataKey="name" stroke="rgba(255,255,255,0.5)" />
                  <YAxis stroke="rgba(255,255,255,0.5)" />
                  <Tooltip
                    contentStyle={{ background: "rgba(0,0,0,0.8)", border: "1px solid rgba(255,255,255,0.1)" }}
                  />
                  <Bar dataKey="usage" fill="#8b5cf6" radius={8} />
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>

            {/* Document History Table */}
            <div className="mb-8">
              <DocumentHistory />
            </div>
          </motion.div>
        </main>
      </div>
    </div>
  )
}
