"use client"

import type React from "react"

import { motion } from "framer-motion"
import { Card } from "@/components/ui/card"
import { Upload, FileText } from "lucide-react"
import { useState, useRef } from "react"
import { validateUploadFile } from "@/lib/input-validation"

interface UploadZoneProps {
  onFileSelect: (file: File) => void
  /** When true, file pick/drag are blocked (e.g. guest session still connecting). */
  disabled?: boolean
  /** Soft status shown inside the upload panel — never a full-page gate. */
  statusMessage?: string | null
}

export function UploadZone({
  onFileSelect,
  disabled = false,
  statusMessage = null,
}: UploadZoneProps) {
  const [isDragging, setIsDragging] = useState(false)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [localError, setLocalError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const acceptFile = (file: File) => {
    const result = validateUploadFile(file)
    if (!result.ok) {
      setLocalError(result.error)
      setSelectedFile(null)
      return
    }
    setLocalError(null)
    setSelectedFile(file)
    onFileSelect(file)
  }

  const handleCardClick = () => {
    if (disabled) return
    fileInputRef.current?.click()
  }

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (disabled) return
    const files = e.target.files
    if (files && files.length > 0) {
      acceptFile(files[0])
    }
    // Allow re-selecting the same file after a rejection
    e.target.value = ""
  }

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    if (disabled) return
    setIsDragging(true)
  }

  const handleDragLeave = () => {
    setIsDragging(false)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    if (disabled) return

    const files = e.dataTransfer.files
    if (files.length > 0) {
      acceptFile(files[0])
    }
  }

  return (
    <motion.div initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.5 }}>
      <Card
        onClick={handleCardClick}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        aria-disabled={disabled}
        className={`p-12 border-2 border-dashed transition-colors ${
          disabled
            ? "cursor-not-allowed border-border/40 bg-card/20 opacity-80"
            : isDragging
              ? "cursor-pointer border-primary bg-primary/10"
              : "cursor-pointer border-border/50 bg-card/30"
        }`}
      >
        <input
          type="file"
          ref={fileInputRef}
          className="hidden"
          onChange={handleFileInputChange}
          accept=".pdf,.docx,.txt,.csv"
          disabled={disabled}
        />
        <motion.div animate={{ scale: isDragging && !disabled ? 1.1 : 1 }} className="flex flex-col items-center justify-center">
          <motion.div animate={{ y: isDragging && !disabled ? -4 : 0 }} transition={{ type: "spring", stiffness: 400 }}>
            <Upload className="w-12 h-12 text-primary/60 mb-4" />
          </motion.div>

          <h3 className="text-lg font-semibold mb-2 text-center">Drop your document here</h3>
          <p className="text-sm text-muted-foreground text-center mb-4">
            or click to browse. Supports PDF, DOCX, TXT, CSV
          </p>
          {statusMessage ? (
            <p className="text-xs text-muted-foreground text-center mb-2" role="status">
              {statusMessage}
            </p>
          ) : null}
          {localError ? (
            <p className="text-xs text-destructive text-center mb-2" role="alert">
              {localError}
            </p>
          ) : null}

          {selectedFile && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="mt-4 flex items-center gap-2 px-4 py-2 bg-primary/20 rounded-lg border border-primary/30"
            >
              <FileText className="w-4 h-4 text-primary" />
              <span className="text-sm text-primary font-medium">{selectedFile.name}</span>
            </motion.div>
          )}
        </motion.div>
      </Card>
    </motion.div>
  )
}
