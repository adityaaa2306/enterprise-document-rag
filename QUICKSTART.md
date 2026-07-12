# Quick Start Guide

## Get Started Locally

You need **three** processes: API, worker, and frontend. The API only queues jobs; the worker runs the LangGraph pipeline.

### 1. Install Dependencies

**Backend:**
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
```

**Frontend:**
```bash
cd frontend
npm install
```

### 2. Environment

**Backend** — copy `.env.example` to `.env` if you do not already have one:

```bash
cd backend
copy .env.example .env  # Windows
# cp .env.example .env  # macOS/Linux
```

Set at least:
```
NVIDIA_API_KEY=your_actual_nvidia_api_key
APP_ENV=development
OBJECT_STORAGE_BACKEND=local
CORS_ALLOW_ALL=true
```

(Get an NVIDIA key at https://build.nvidia.com/settings/api-keys)

**Frontend** — create `frontend/.env.local`:
```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### 3. Start All Three Servers

**Terminal 1 — API (port 8000):**
```bash
cd backend
.venv\Scripts\activate
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2 — Worker (required for document processing):**
```bash
cd backend
.venv\Scripts\activate
python -m src.worker
```

**Terminal 3 — Frontend (port 3000):**
```bash
cd frontend
npm run dev
```

### 4. Open the App

- Frontend: http://localhost:3000
- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/api/health
- Worker health: http://localhost:8000/api/worker/health

### 5. First Document

1. Sign up at http://localhost:3000/signup
2. Log in
3. New Job → upload a PDF → Process
4. Results page polls until the worker finishes

---

## Troubleshooting

**`net::ERR_CONNECTION_REFUSED` on `/summarize`**
- The browser cannot reach the API. Start Terminal 1 (uvicorn on port 8000).
- Confirm `NEXT_PUBLIC_API_URL` in `frontend/.env.local` is `http://localhost:8000`.
- Restart `npm run dev` after changing `.env.local`.

**Upload succeeds but job stays pending**
- The worker is not running. Start Terminal 2: `python -m src.worker`.

**CORS errors in the browser console**
- Locally set `CORS_ALLOW_ALL=true` or include `http://localhost:3000` in `CORS_ORIGINS`.

**Models / summarization fail**
- Verify `NVIDIA_API_KEY` in `backend/.env`.

**Using the Vercel frontend**
- It must point at a live API (`NEXT_PUBLIC_API_URL`). A sleeping or stopped Render service causes connection failures. Prefer local API+worker for development.

---

## Production note

**Supported cloud topology (embedded Chroma):** one Render Web Service with
`RUN_EMBEDDED_WORKER=true` so the API and worker share `/data/chroma`.

A separate Background Worker with its own Render disk **breaks RAG** (worker
writes vectors the API cannot read). Local `docker compose` is fine with
separate containers because they mount the same named volume.

See `backend/docs/RENDER_DEPLOYMENT.md` and repo-root `render.yaml`.
