"use client"

import type React from "react"

import { motion } from "framer-motion"
import { Card } from "@/components/ui/card"
import { Upload, FileText } from "lucide-react"
import { useState, useRef } from "react"

interface UploadZoneProps {
  onFileSelect: (file: File) => void
}

export function UploadZone({ onFileSelect }: UploadZoneProps) {
  const [isDragging, setIsDragging] = useState(false)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleCardClick = () => {
    fileInputRef.current?.click()
  }

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (files && files.length > 0) {
      const file = files[0]
      setSelectedFile(file)
      onFileSelect(file)
    }
  }

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }

  const handleDragLeave = () => {
    setIsDragging(false)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)

    const files = e.dataTransfer.files
    if (files.length > 0) {
      const file = files[0]
      setSelectedFile(file)
      onFileSelect(file)
    }
  }

  return (
    <motion.div initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.5 }}>
      <Card
        onClick={handleCardClick}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={`p-12 border-2 border-dashed transition-colors cursor-pointer ${isDragging ? "border-primary bg-primary/10" : "border-border/50 bg-card/30"
          }`}
      >
        <input
          type="file"
          ref={fileInputRef}
          className="hidden"
          onChange={handleFileInputChange}
          accept=".pdf,.docx,.txt,.csv"
        />
        <motion.div animate={{ scale: isDragging ? 1.1 : 1 }} className="flex flex-col items-center justify-center">
          <motion.div animate={{ y: isDragging ? -4 : 0 }} transition={{ type: "spring", stiffness: 400 }}>
            <Upload className="w-12 h-12 text-primary/60 mb-4" />
          </motion.div>

          <h3 className="text-lg font-semibold mb-2 text-center">Drop your document here</h3>
          <p className="text-sm text-muted-foreground text-center mb-4">
            or click to browse. Supports PDF, DOCX, TXT, CSV
          </p>

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
