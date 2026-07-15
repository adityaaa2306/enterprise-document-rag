# Production Deployment Checklist

Use this before opening the app to public users.  
Platforms: **Vercel** + **Render** + **Neon** + **Cloudflare R2** + **NVIDIA NIM**.

---

## A. Secrets & environment (must complete)

### Render (Web Service `green-agentic-api`)

- [ ] `APP_ENV=production`
- [ ] `DATABASE_URL` = Neon **pooled** URL with SSL (`postgresql://…` or `postgresql+psycopg://…`)
- [ ] `JWT_SECRET_KEY` generated (Blueprint `generateValue` or manual)
- [ ] `NVIDIA_API_KEY` set (optional peer keys if using pool)
- [ ] `OBJECT_STORAGE_BACKEND=r2`
- [ ] `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`
- [ ] `CORS_ORIGINS=https://<your-vercel-app>.vercel.app` (or `*` for open SPA demos)
- [ ] `CORS_ALLOW_ALL=false`
- [ ] `RUN_EMBEDDED_WORKER=true`
- [ ] `WORKER_ID=embedded-api-1`
- [ ] `CHROMA_PERSIST_DIRECTORY=/data/chroma`
- [ ] `VECTOR_DB_PATH=/data/aux`
- [ ] `ROUTING_TELEMETRY_PATH=/data/aux/routing_telemetry.jsonl`
- [ ] `RUN_MIGRATIONS_ON_STARTUP=true`
- [ ] `AUTO_CREATE_SCHEMA=false`
- [ ] Docker Build Target = **`api`**
- [ ] Health Check Path = `/api/health`
- [ ] Docker Command = `/app/scripts/docker-entrypoint-api.sh`

### Vercel (Root Directory = `frontend`)

- [ ] `NEXT_PUBLIC_API_URL=https://<your-api>.onrender.com` (Production + Preview as needed)
- [ ] Optional: `NEXT_PUBLIC_JOB_POLL_TIMEOUT_MS`
- [ ] Framework preset: Next.js
- [ ] Confirm build uses `next build` / `next start`

---

## B. Post-deploy smoke

```bash
set API_URL=https://<api>.onrender.com
set FRONTEND_URL=https://<app>.vercel.app
set SMOKE_EMAIL=smoke@example.com
set SMOKE_PASSWORD=SecurePass123!
cd backend
python scripts/smoke_production.py
```

Manual probes:

- [ ] `GET /api/health` → 200 `status=ok|starting`
- [ ] `GET /api/ready` → 200 (DB + Chroma + R2)
- [ ] `GET /api/worker/health` → `alive_count >= 1`
- [ ] Browser Network tab hits **API host**, not `localhost:8000`
- [ ] Login → upload PDF → Results polls → Summary Ready → Search Ready
- [ ] Carbon metrics populate without manual Refresh
- [ ] Chat / RAG returns answers

---

## C. Optional hardening

- [ ] Attach paid Render disk at `/data` (persist Chroma across restarts)
- [ ] Upgrade Render plan if free-tier OOM / sleep is unacceptable
- [ ] Add Vercel preview origins to `CORS_ORIGINS` (or use `*`)
- [ ] Pause Results polling when `document.hidden` (future UX; not required)

---

## D. Changes made during deployment validation (2026-07-15)

| Change | File(s) |
|--------|---------|
| Fail-fast: Postgres, NIM, R2, non-localhost CORS in production | `backend/src/core/config.py` |
| Expanded production config tests | `backend/tests/test_phase0_health_config.py` |
| Production build requires `NEXT_PUBLIC_API_URL` | `frontend/config.ts` |
| Icon assets fixed (missing PNGs → SVG) | `frontend/app/layout.tsx` |
| Frontend env example | `frontend/.env.example` |
| Telemetry path under `/data` | `render.yaml`, `backend/render.yaml`, `docker-entrypoint-api.sh` |
| Environment catalog | `backend/docs/DEPLOYMENT_ENVIRONMENT.md` |
| Readiness report | `backend/docs/DEPLOYMENT_READINESS_REPORT.md` |

---

## E. Do not change (frozen)

- Adaptive chunking, CRE, QVA, routing heuristics, prompts, carbon methodology, summarization quality
- Topology: single API + embedded worker + embedded Chroma

---

## F. Go / No-go

**GO** when sections A and B are checked and smoke passes.

**NO-GO** if:

- `/api/ready` stays 503 (DB/R2/Chroma)
- Frontend calls `localhost`
- Worker `alive_count=0`
- Production process starts with SQLite (should crash at validate)

Reference: `DEPLOYMENT_READINESS_REPORT.md`, `DEPLOYMENT_ENVIRONMENT.md`, `RENDER_DEPLOYMENT.md`.
