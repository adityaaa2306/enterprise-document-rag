import type { MetadataRoute } from "next"

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: ["/dashboard", "/results", "/settings", "/new-job"],
    },
    sitemap: "https://enterprise-document-rag.vercel.app/sitemap.xml",
  }
}
