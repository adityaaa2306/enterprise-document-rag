import type React from "react"
import type { Metadata } from "next"
import { Inter, JetBrains_Mono } from "next/font/google"
import "./globals.css"

const _sans = Inter({ subsets: ["latin"], variable: "--font-sans", display: "swap" })
const _mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono", display: "swap" })

export const metadata: Metadata = {
  title: "Green Agentic | Carbon-Aware Document Intelligence",
  description:
    "Capability-first Light/Medium/Heavy routing on NVIDIA NIM, Boundary-A carbon accounting, and Interactive RAG — with Document Processing CO₂e tracked separately.",
  metadataBase: new URL("https://enterprise-document-rag.vercel.app"),
  openGraph: {
    title: "Green Agentic | Carbon-Aware Document Intelligence",
    description:
      "CRE + QVA routing, Document Processing vs Interactive RAG carbon, single-region Electricity Maps intensity.",
    url: "https://enterprise-document-rag.vercel.app",
    siteName: "Green Agentic",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "Green Agentic | Carbon-Aware Document Intelligence",
    description:
      "CRE + QVA routing, Document Processing vs Interactive RAG carbon, single-region Electricity Maps intensity.",
  },
  icons: {
    icon: [{ url: "/icon.svg", type: "image/svg+xml" }],
    apple: "/icon.svg",
  },
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en" className={`dark ${_sans.variable} ${_mono.variable}`}>
      <body className={`${_sans.className} antialiased bg-background text-foreground`}>
        {children}
      </body>
    </html>
  )
}
