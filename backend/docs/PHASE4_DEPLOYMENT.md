# Phase 4 — Docker + Render + Neon + R2

**Superseded for cloud deploy by:** [`RENDER_DEPLOYMENT.md`](./RENDER_DEPLOYMENT.md)

Railway configs have been **removed**. Production target is **Render**.

AI pipeline unchanged.

```mermaid
flowchart TB
  Vercel[Vercel Next.js] --> API[Render Web — FastAPI]
  API --> Neon[(Neon)]
  API --> R2[(R2)]
  API --> Chroma[Render Chroma]
  Worker[Render Worker] --> Neon
  Worker --> R2
  Worker --> Chroma
```

Local: `docker compose up --build`  
Cloud: see **RENDER_DEPLOYMENT.md**
