
"use client"

import { useState, useEffect } from "react"
import { motion } from "framer-motion"
import { FileText, Download, Clock } from "lucide-react"
import { apiFetch } from "@/lib/api"

interface Document {
    document_id: string
    summary: string
    saved_at: string
}

export function DocumentHistory() {
    const [documents, setDocuments] = useState<Document[]>([])
    const [loading, setLoading] = useState(true)

    useEffect(() => {
        fetchDocuments()
    }, [])

    const fetchDocuments = async () => {
        try {
            const res = await apiFetch("/documents")
            if (res.ok) {
                const data = await res.json()
                setDocuments(data)
            }
        } catch (error) {
            console.error("Failed to fetch documents:", error)
        } finally {
            setLoading(false)
        }
    }

    const handleDownload = (doc: Document) => {
        const element = document.createElement("a")
        const file = new Blob([doc.summary], { type: "text/plain" })
        element.href = URL.createObjectURL(file)
        element.download = `summary-${doc.document_id}.txt`
        document.body.appendChild(element)
        element.click()
        document.body.removeChild(element)
    }

    if (loading) return <div className="text-white/50">Loading history...</div>

    return (
        <div className="bg-white/5 backdrop-blur-md border border-white/10 rounded-xl p-6">
            <h2 className="text-xl font-bold mb-4 flex items-center gap-2">
                <Clock className="w-5 h-5 text-purple-400" />
                Processed Documents History
            </h2>

            <div className="overflow-x-auto">
                <table className="w-full text-left">
                    <thead>
                        <tr className="border-b border-white/10 text-white/50 text-sm">
                            <th className="pb-3 pl-2">Document ID</th>
                            <th className="pb-3">Date Processed</th>
                            <th className="pb-3 text-right pr-2">Actions</th>
                        </tr>
                    </thead>
                    <tbody className="text-sm">
                        {documents.length === 0 ? (
                            <tr>
                                <td colSpan={3} className="py-8 text-center text-white/30">
                                    No documents found. Process a new job to see it here.
                                </td>
                            </tr>
                        ) : (
                            documents.map((doc) => (
                                <tr key={doc.document_id} className="border-b border-white/5 hover:bg-white/5 transition-colors">
                                    <td className="py-3 pl-2 font-mono text-purple-300">
                                        {doc.document_id.substring(0, 8)}...
                                    </td>
                                    <td className="py-3 text-white/70">
                                        {new Date(doc.saved_at).toLocaleString()}
                                    </td>
                                    <td className="py-3 text-right pr-2">
                                        <button
                                            onClick={() => handleDownload(doc)}
                                            className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-purple-500/20 hover:bg-purple-500/30 text-purple-300 rounded-md text-xs transition-colors"
                                        >
                                            <Download className="w-3 h-3" />
                                            Download Summary
                                        </button>
                                        {/* Optional: Add View button later */}
                                    </td>
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>
        </div>
    )
}
