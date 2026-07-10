"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { motion } from "framer-motion"
import { Sidebar } from "@/components/sidebar"
import { TopBar } from "@/components/top-bar"
import { UploadZone } from "@/components/upload-zone"
import { SmartRoutingPanel } from "@/components/smart-routing-panel"
import { apiFetch } from "@/lib/api"
import type { RoutingPreference } from "@/lib/routing"

export default function NewJobPage() {
  const router = useRouter()
  const [step, setStep] = useState<"upload" | "confirm">("upload")
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [preference, setPreference] = useState<RoutingPreference>("automatic")
  const [isSubmitting, setIsSubmitting] = useState(false)

  const handleFileSelect = (file: File) => {
    setSelectedFile(file)
    setStep("confirm")
  }

  const handleSubmit = async () => {
    if (!selectedFile || isSubmitting) return
    setIsSubmitting(true)
    try {
      const formData = new FormData()
      formData.append("file", selectedFile)

      const response = await apiFetch(
        `/summarize?mode=${encodeURIComponent(preference)}`,
        { method: "POST", body: formData },
      )

      if (!response.ok) {
        throw new Error("Upload failed")
      }

      const data = await response.json()
      router.push(`/results?job_id=${data.job_id}`)
    } catch (error) {
      console.error("Error uploading file:", error)
      alert("Failed to start job. Please try again.")
      setIsSubmitting(false)
    }
  }

  return (
    <div className="flex">
      <Sidebar />
      <div className="flex-1">
        <TopBar />
        <main className="p-8">
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <h1 className="text-3xl font-bold mb-2">Process a document</h1>
            <p className="text-muted-foreground mb-8">
              Upload a file. Smart Routing selects models automatically — no manual mode choice.
            </p>

            {step === "upload" || !selectedFile ? (
              <UploadZone onFileSelect={handleFileSelect} />
            ) : (
              <SmartRoutingPanel
                fileName={selectedFile.name}
                preference={preference}
                onPreferenceChange={setPreference}
                onSubmit={handleSubmit}
                onBack={() => {
                  setSelectedFile(null)
                  setStep("upload")
                }}
                isSubmitting={isSubmitting}
              />
            )}
          </motion.div>
        </main>
      </div>
    </div>
  )
}
