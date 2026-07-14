import type React from "react"
import type { Metadata } from "next"
import { Inter, JetBrains_Mono } from "next/font/google"
import "./globals.css"

const _sans = Inter({ subsets: ["latin"], variable: "--font-sans", display: "swap" })
const _mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono", display: "swap" })

export const metadata: Metadata = {
  title: "Green Agentic | Carbon-Aware Document Intelligence",
  description:
    "A document processing pipeline that decides, per chunk, which model to run — and where — for transparent carbon accounting.",
  generator: "v0.app",
  icons: {
    icon: [
      {
        url: "/icon-light-32x32.png",
        media: "(prefers-color-scheme: light)",
      },
      {
        url: "/icon-dark-32x32.png",
        media: "(prefers-color-scheme: dark)",
      },
      {
        url: "/icon.svg",
        type: "image/svg+xml",
      },
    ],
    apple: "/apple-icon.png",
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
