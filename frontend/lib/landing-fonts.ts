import { Outfit, IBM_Plex_Sans, Cormorant_Garamond } from "next/font/google"

/** Landing-only fonts — imported by the homepage so app routes do not pay for them. */
export const landingDisplay = Outfit({
  subsets: ["latin"],
  variable: "--font-landing-display",
  weight: ["300", "400", "500", "600", "700"],
  display: "swap",
})

export const landingBody = IBM_Plex_Sans({
  subsets: ["latin"],
  variable: "--font-landing-body",
  weight: ["300", "400", "500", "600"],
  display: "swap",
})

export const landingSerif = Cormorant_Garamond({
  subsets: ["latin"],
  variable: "--font-landing-serif",
  weight: ["300", "400", "500", "600", "700"],
  style: ["normal", "italic"],
  display: "swap",
})
