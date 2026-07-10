# Phase 5 — Production Launch & Operational Validation

**Status:** Launch kit ready. Fill URLs after Vercel + **Render** go live, then run the smoke test.

**Backend platform:** Render (Railway removed). See [`RENDER_DEPLOYMENT.md`](./RENDER_DEPLOYMENT.md).

**Scope:** Prove the existing architecture works in production.  
**Out of scope:** New features, AI redesign.

---

## 1. Deployment URLs

| Surface | URL | Notes |
|---------|-----|-------|
| Frontend (Vercel) | `_TBD — https://<project>.vercel.app_` | |
| Backend API (Render) | `_TBD — https://<api>.onrender.com_` | Public HTTPS |
| Worker (Render) | _(no public URL)_ | Check `/api/worker/health` |
| Neon Postgres | _(connection string)_ | Private |
| Cloudflare R2 | _(bucket)_ | |
| Chroma (Render private) | _(internal host)_ | `CHROMA_SERVER_HOST` |

---

## 2. Deploy steps

### A. Backend on Render
Follow **RENDER_DEPLOYMENT.md** (Chroma + API Web Service + Background Worker + Neon + R2).

Confirm:
- `GET /api/health` → 200  
- `GET /api/ready` → 200  
- `GET /api/worker/health` → 200  

### B. Vercel frontend
```bash
cd frontend
npx vercel env add NEXT_PUBLIC_API_URL production
# value: https://<your-api>.onrender.com
npx vercel --prod
```

### C. CORS on Render API
```
APP_ENV=production
CORS_ALLOW_ALL=false
CORS_ORIGINS=https://<project>.vercel.app
```

### D. Smoke test
```bash
cd backend
set API_URL=https://<api>.onrender.com
set FRONTEND_URL=https://<app>.vercel.app
python scripts/smoke_production.py
```

---

## 3. Environment checklist

See `RENDER_DEPLOYMENT.md` §4 and `.env.production.example`.

| Surface | Key vars |
|---------|----------|
| Vercel | `NEXT_PUBLIC_API_URL` |
| Render API | Neon, JWT, CORS, R2, NIM, `CHROMA_MODE=http`, `CHROMA_SERVER_HOST` |
| Render Worker | Same DB/R2/NIM/Chroma; `RUN_MIGRATIONS_ON_STARTUP=false`; `WORKER_ID` |

---

## 4. Verification checklist

| # | Check | Pass? |
|---|-------|:-----:|
| 1 | Frontend on Vercel | ☐ |
| 2 | Env vars (Vercel + Render) | ☐ |
| 3 | Frontend → Render API | ☐ |
| 4 | CORS | ☐ |
| 5 | Auth | ☐ |
| 6 | Uploads | ☐ |
| 7 | R2 | ☐ |
| 8 | Neon Postgres | ☐ |
| 9 | Worker processing | ☐ |
| 10 | Chroma retrieval | ☐ |
| 11 | Conversations | ☐ |
| 12 | Job polling | ☐ |
| 13 | Logging (`request_id=…`) | ☐ |
| 14 | Smoke script exit 0 | ☐ |

---

## 5. Rollback

- **Vercel:** Promote previous production deployment  
- **Render API / Worker:** Redeploy previous successful deploy  
- **Neon:** PITR / branch restore if migration issue  
- **Stuck jobs:** wait claim timeout or set `pending`  

---

## 6. Troubleshooting

| Symptom | Fix |
|---------|-----|
| CORS errors | Add exact Vercel origin to `CORS_ORIGINS` on Render API |
| Frontend hits localhost | Set `NEXT_PUBLIC_API_URL` → redeploy Vercel |
| Jobs stay pending | Worker down / wrong `DATABASE_URL` / check `/api/worker/health` |
| Ready chroma fail | `CHROMA_SERVER_HOST` + Chroma service disk |
| R2 errors | `OBJECT_STORAGE_BACKEND=r2` + keys |

Full backend setup: **RENDER_DEPLOYMENT.md**.
