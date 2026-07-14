import HomeClient from "./home-client"
import {
  landingDisplay,
  landingBody,
  landingSerif,
} from "@/lib/landing-fonts"

export default function Home() {
  return (
    <div
      className={`${landingDisplay.variable} ${landingBody.variable} ${landingSerif.variable}`}
    >
      <HomeClient />
    </div>
  )
}
