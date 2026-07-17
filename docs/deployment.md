# Deployment

How to run Green Agentic RAG locally and how the production portfolio stack is usually wired (Vercel frontend + Render API).

---

## 1. Architecture in production

```
Browser
  → Vercel (Next.js frontend)
      → HTTPS + Bearer token
  → Render Web Service (FastAPI + embedded worker)
      → Neon PostgreSQL
      → Cloudflare R2 (documents)
      → Chroma on disk (/data) when available
      → NVIDIA NIM APIs
```

**Important portfolio default:** one Render Web Service with `RUN_EMBEDDED_WORKER=true`. The job worker runs **inside** the API process so it shares Chroma/NIM memory. Do not start a second worker process on free tier — that often causes OOM / 502.

---

## 2. Local development

### Prerequisites

- Python 3.10+  
- Node.js 18+  
- NVIDIA API key from [build.nvidia.com](https://build.nvidia.com/settings/api-keys)  
- Optional: Electricity Maps API key for live grid intensity  
- Optional system deps for PDF/OCR (`tesseract`, `poppler`) if you use heavy document parsing

### Backend

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
# source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env   # then edit NVIDIA_API_KEY, JWT_SECRET_KEY, etc.

uvicorn src.api.main:app --reload --host 127.0.0.1 --port 8000
```

- API: http://127.0.0.1:8000  
- OpenAPI docs: http://127.0.0.1:8000/docs  

### Frontend

```bash
cd frontend
npm install
npm run dev
```

- App: http://localhost:3000  
- Point `NEXT_PUBLIC_API_URL` (or `.env.local`) at `http://127.0.0.1:8000` for local API.

### Smoke checklist (local)

1. Open homepage / login or guest.  
2. Upload a small PDF on New Job.  
3. Watch Live Job Status → Summary Ready.  
4. Confirm Document Processing carbon tiles populate.  
5. Ask a chat question; confirm answer + Interactive RAG carbon card.

---

## 3. Essential environment variables

### Backend (high signal)

| Variable | Purpose |
|----------|---------|
| `NVIDIA_API_KEY` | NIM LLMs, embed, rerank |
| `JWT_SECRET_KEY` | Auth tokens (strong random in production) |
| `DATABASE_URL` | SQLite locally; Neon Postgres in production |
| `CORS_ORIGINS` | Frontend origin(s), comma-separated |
| `ELECTRICITY_MAPS_API_KEY` | Live intensity (optional; fallback intensity otherwise) |
| `REGION_SCHEDULER_*` | Single-region scheduler config |
| Light/Medium/Heavy model ids | Primary + fallbacks (see `.env.example`) |
| `EMBEDDING_MODEL` / `RERANK_MODEL` | Retrieval stack |

### Frontend

| Variable | Purpose |
|----------|---------|
| `NEXT_PUBLIC_API_URL` | Public API base URL (no trailing slash issues) |

Never put server secrets in `NEXT_PUBLIC_*` variables.

---

## 4. Production (Vercel + Render)

### Frontend (Vercel)

| Setting | Value |
|---------|--------|
| Root Directory | `frontend` |
| Framework | Next.js |
| Env | `NEXT_PUBLIC_API_URL=https://<your-api>.onrender.com` |

### Backend (Render Web Service)

| Setting | Value |
|---------|--------|
| Root Directory | `backend` |
| Dockerfile | `Dockerfile` |
| Docker Build Target | **`api`** (required) |
| Docker Command | `/app/scripts/docker-entrypoint-api.sh` |
| Health Check | `/api/health` |
| Env highlights | `APP_ENV=production`, Neon `DATABASE_URL`, `JWT_SECRET_KEY`, `NVIDIA_API_KEY`, R2 creds, `RUN_EMBEDDED_WORKER=true`, `CHROMA_PERSIST_DIRECTORY=/data/chroma`, `CORS_ORIGINS=<vercel origin>` |

Blueprint: repo `render.yaml` (and/or `backend/render.yaml`).

### Object storage & DB

| Service | Role |
|---------|------|
| **Neon** | Postgres (`DATABASE_URL` with SSL) |
| **Cloudflare R2** | Uploaded documents (`OBJECT_STORAGE_BACKEND=r2`) |

### Free-tier realities

- Render may **sleep** after idle; first request is a cold start.  
- Without a paid disk, Chroma on `/data` may be lost on redeploy — re-ingest after wake.  
- Prefer `CORS_ORIGINS` set to your Vercel URL; `*` is acceptable for open Bearer-token demos.

---

## 5. Post-deploy smoke

```bash
# health
curl -s https://<api>.onrender.com/api/health
curl -s https://<api>.onrender.com/api/ready
curl -s https://<api>.onrender.com/api/worker/health
```

Manual:

1. Browser Network tab hits the **API host**, not `localhost`.  
2. Login → upload → Results polling → Summary Ready → Search Ready.  
3. Carbon metrics appear without a manual hack.  
4. Chat returns grounded answers.

Optional scripted smoke (when present):

```bash
cd backend
python scripts/smoke_production.py
```

---

## 6. Security checklist (minimum)

- [ ] Strong `JWT_SECRET_KEY` only in the secret store  
- [ ] Postgres not publicly open on `0.0.0.0:5432`  
- [ ] `FORCE_HTTPS` / secure cookies as configured for production  
- [ ] Abuse / rate limits enabled on the API  
- [ ] No NIM keys or JWT secrets in the frontend env  

---

## 7. Syncing benchmark UI data

Benchmarks are static files. After adding/removing campaigns:

```powershell
.\scripts\sync-benchmark-campaigns.ps1
```

See [benchmark-methodology.md](./benchmark-methodology.md).

---

## 8. Troubleshooting

| Symptom | Likely cause |
|---------|----------------|
| Frontend loads, API 502 | Render cold start / OOM — check logs; avoid dual workers |
| CORS errors | `CORS_ORIGINS` missing Vercel origin |
| Jobs stuck | Worker not embedded / `/api/worker/health` dead |
| Empty vectors after redeploy | Ephemeral disk — re-ingest |
| Carbon always fallback intensity | Missing EM key or scheduler config |

---

## Related docs

- [architecture.md](./architecture.md)  
- Engineer deep-dives: [`backend/docs/RENDER_DEPLOYMENT.md`](../backend/docs/RENDER_DEPLOYMENT.md), [`PRODUCTION_DEPLOYMENT_CHECKLIST.md`](../backend/docs/PRODUCTION_DEPLOYMENT_CHECKLIST.md)  
- Quick start also in [`../README.md`](../README.md) and [`../backend/README.md`](../backend/README.md)
