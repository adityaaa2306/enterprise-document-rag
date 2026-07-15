"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { motion } from "framer-motion"
import { Sidebar } from "@/components/sidebar"
import { TopBar } from "@/components/top-bar"
import { GuestOwnerGate } from "@/components/guest-owner-gate"
import { UploadZone } from "@/components/upload-zone"
import { SmartRoutingPanel } from "@/components/smart-routing-panel"
import { getAccessToken } from "@/lib/api"
import { rememberJobId } from "@/lib/job-session"
import type { RoutingPreference } from "@/lib/routing"
import { JobQueuePanel } from "@/components/job-queue-panel"
import { API_BASE_URL } from "@/config"
import { getGuestSessionId } from "@/lib/guest-session"

function uploadSummarize(
  file: File,
  preference: string,
  onProgress: (pct: number) => void,
): Promise<{ job_id: string }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const url = `${API_BASE_URL}/summarize?mode=${encodeURIComponent(preference)}`
    xhr.open("POST", url)
    const token = getAccessToken()
    if (token) {
      xhr.setRequestHeader("Authorization", `Bearer ${token}`)
    } else {
      const guestId = getGuestSessionId()
      if (guestId) xhr.setRequestHeader("X-Guest-Session-Id", guestId)
    }
    // Header-based auth — credentials break CORS when Allow-Origin is *
    xhr.withCredentials = false

    xhr.upload.onprogress = (ev) => {
      if (!ev.lengthComputable) return
      onProgress(Math.min(99, Math.round((ev.loaded / ev.total) * 100)))
    }
    xhr.onload = () => {
      if (xhr.status === 401) {
        reject(new Error("Authentication expired. Please sign in again."))
        return
      }
      let body: { job_id?: string; detail?: string } = {}
      try {
        body = JSON.parse(xhr.responseText || "{}")
      } catch {
        /* ignore */
      }
      if (xhr.status < 200 || xhr.status >= 300) {
        const detail =
          typeof body?.detail === "string" ? body.detail : "Upload failed"
        reject(new Error(`${detail} (HTTP ${xhr.status})`))
        return
      }
      if (!body.job_id) {
        reject(new Error("Upload succeeded but no job_id returned"))
        return
      }
      onProgress(100)
      resolve({ job_id: body.job_id })
    }
    xhr.onerror = () =>
      reject(
        new TypeError(
          `Cannot reach API at ${API_BASE_URL}. Start the backend, then retry.`,
        ),
      )
    xhr.onabort = () => reject(new Error("Upload cancelled"))

    const formData = new FormData()
    formData.append("file", file)
    xhr.send(formData)
  })
}

export default function NewJobPage() {
  const router = useRouter()
  const [step, setStep] = useState<"upload" | "confirm">("upload")
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [preference, setPreference] = useState<RoutingPreference>("automatic")
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [uploadPct, setUploadPct] = useState<number | null>(null)

  const handleFileSelect = (file: File) => {
    setSelectedFile(file)
    setStep("confirm")
  }

  const handleSubmit = async () => {
    if (!selectedFile || isSubmitting) return
    setIsSubmitting(true)
    setUploadPct(0)
    try {
      const data = await uploadSummarize(selectedFile, preference, setUploadPct)
      rememberJobId(data.job_id)
      router.push(`/results?job_id=${data.job_id}`)
    } catch (error) {
      console.error("Error uploading file:", error)
      const msg =
        error instanceof Error
          ? error.message
          : "Failed to start job. Please try again."
      alert(msg)
      setIsSubmitting(false)
      setUploadPct(null)
    }
  }

  return (
    <GuestOwnerGate>
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

            <div className="grid grid-cols-1 xl:grid-cols-4 gap-6">
              <div className="xl:col-span-1">
                <JobQueuePanel deferPolling={isSubmitting} />
              </div>
              <div className="xl:col-span-3">
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
                    uploadPct={uploadPct}
                  />
                )}
              </div>
            </div>
          </motion.div>
        </main>
      </div>
    </div>
    </GuestOwnerGate>
  )
}
