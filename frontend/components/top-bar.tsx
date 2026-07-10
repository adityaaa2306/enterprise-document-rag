"use client"

import { motion } from "framer-motion"
import { Bell, User } from "lucide-react"

export function TopBar() {
  return (
    <motion.header
      initial={{ y: -60 }}
      animate={{ y: 0 }}
      className="border-b border-border bg-card/50 backdrop-blur sticky top-0 z-40"
    >
      <div className="px-8 py-4 flex justify-between items-center">
        <h2 className="text-xl font-semibold text-balance">Platform Dashboard</h2>

        <div className="flex items-center gap-4">
          <motion.button
            whileHover={{ scale: 1.1 }}
            whileTap={{ scale: 0.95 }}
            className="relative p-2 rounded-lg hover:bg-card text-muted-foreground hover:text-foreground transition-colors"
          >
            <Bell className="w-5 h-5" />
            <span className="absolute top-1 right-1 w-2 h-2 bg-destructive rounded-full" />
          </motion.button>

          <div className="w-px h-6 bg-border" />

          <div className="flex items-center gap-3">
            <div className="text-right text-sm">
              <p className="font-medium">Sustainability Manager</p>
              <p className="text-xs text-muted-foreground">Admin</p>
            </div>
            <div className="w-8 h-8 rounded-full bg-primary/20 flex items-center justify-center">
              <User className="w-4 h-4 text-primary" />
            </div>
          </div>
        </div>
      </div>
    </motion.header>
  )
}
