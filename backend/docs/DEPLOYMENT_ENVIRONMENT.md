# Deployment Environment Variables

**Platforms:** Render (API) · Vercel (Next.js) · Neon (Postgres) · Cloudflare R2 · NVIDIA NIM  
**Last validated:** 2026-07-15  

Startup enforcement lives in `Settings.validate_for_runtime()` (`backend/src/core/config.py`).  
Production (`APP_ENV=production`) **fails fast** on missing Postgres, JWT, NIM, R2 (when backend=r2), and localhost-only CORS.

---

## Deploy-critical

| Variable | Purpose | Required | Default | Used by | Failure if missing |
|----------|---------|----------|---------|---------|-------------------|
| `APP_ENV` | Environment tier | Yes (prod) | `development` | config, health, validation | Prod safety rules not applied |
| `SERVICE_ROLE` | `api` vs `worker` | Blueprint: `api` | (none) | CORS skip for workers | CORS enforced on API (OK) |
| `PORT` | HTTP bind | Yes (Render) | `8000` | entrypoint, uvicorn | Health check fails |
| `DATABASE_URL` | Neon Postgres | **Yes in prod** | `sqlite:///./agentic_db.sqlite` | SQLAlchemy, Alembic, jobs | **Startup RuntimeError** (SQLite rejected in prod) |
| `JWT_SECRET_KEY` | JWT signing | **Yes in prod** | `""` | auth | **Startup RuntimeError** |
| `CORS_ORIGINS` | Allowed browser origins | **Yes for API** | localhost:3000 | CORSMiddleware | Empty → RuntimeError; localhost-only → RuntimeError in prod |
| `CORS_ALLOW_ALL` | Dev open CORS | Set `false` | `true` | cors helpers | Ignored in production |
| `NVIDIA_API_KEY` | Primary NIM key | **Yes in prod** | `""` | models, endpoint pool | **Startup RuntimeError** if no NIM keys |
| `NVIDIA_BASE_URL` | NIM base URL | No | NVIDIA integrate | models | Wrong endpoint if mis-set |
| `OBJECT_STORAGE_BACKEND` | `local` / `r2` / `s3` | Yes | `local` | storage factory | Blueprint sets `r2` |
| `R2_ACCOUNT_ID` | R2 account | If r2 | `""` | storage | **Startup RuntimeError** in prod when backend=r2 |
| `R2_ACCESS_KEY_ID` | R2 access key | If r2 | `""` | storage | same |
| `R2_SECRET_ACCESS_KEY` | R2 secret | If r2 | `""` | storage | same |
| `R2_BUCKET` | Bucket name | If r2 | `""` | storage | same |
| `R2_ENDPOINT_URL` | Custom endpoint | No | derived | storage | Uses default R2 URL |
| `R2_PUBLIC_BASE_URL` | Public URL prefix | No | `""` | storage | `file_url` may be null |
| `CHROMA_PERSIST_DIRECTORY` | Embeddings path | Yes | `./local_db/chroma` | chroma | Blueprint: `/data/chroma` |
| `VECTOR_DB_PATH` | BM25 / aux / cache | Yes | `./local_db/aux` | bm25, caches | Blueprint: `/data/aux` |
| `ROUTING_TELEMETRY_PATH` | JSONL telemetry | No | `./local_db/...` | routing telemetry | Blueprint: `/data/aux/routing_telemetry.jsonl` |
| `CHROMA_COLLECTION_NAME` | Collection | Yes | `documents_nemotron_v2` | chroma | Wrong collection |
| `RUN_MIGRATIONS_ON_STARTUP` | Alembic on boot | Recommended | `false` (code) / `true` (yaml) | entrypoint | Schema missing → `/api/ready` 503 |
| `AUTO_CREATE_SCHEMA` | `create_all` | Must be false | `false` | storage | Forced off in prod |
| `RUN_EMBEDDED_WORKER` | In-process worker | **Yes (portfolio)** | `false` | lifespan | Jobs never claimed; worker health 503 |
| `WORKER_ID` | Worker identity | Recommended | auto | worker loop | Auto hostname-pid |
| `PERSIST_JOBS_TO_DB` | Durable jobs | Yes | `true` | jobs | In-memory only if false |
| `PERSIST_CONVERSATIONS_TO_DB` | Durable chats | Yes | `true` | conversations | File fallback |
| `PERSIST_ROUTING_EVENTS_TO_DB` | Routing events | Yes | `true` | telemetry | JSONL-only |

---

## Frontend (Vercel)

| Variable | Purpose | Required | Default | Used by | Failure if missing |
|----------|---------|----------|---------|---------|-------------------|
| `NEXT_PUBLIC_API_URL` | API origin (no trailing slash) | **Yes in prod build** | localhost:8000 (dev only) | `frontend/config.ts` → all API calls | **Build throws** when `NODE_ENV=production` |
| `NEXT_PUBLIC_JOB_POLL_TIMEOUT_MS` | Results poll budget | No | `2700000` | `app/results/page.tsx` | Polls stop after 45m |

---

## Auth cookies (optional)

| Variable | Purpose | Required | Default | Used by | Failure if missing |
|----------|---------|----------|---------|---------|-------------------|
| `JWT_ALGORITHM` | JWT alg | No | `HS256` | auth | — |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access TTL | No | `30` | auth | — |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh TTL | No | `14` | auth | — |
| `AUTH_COOKIE_ENABLED` | httpOnly refresh cookie | No | `false` | main | Body tokens only (SPA default) |
| `AUTH_COOKIE_SECURE` | Secure cookie | If cookies | `false` | main | Warning in prod if cookies + insecure |
| `AUTH_COOKIE_SAMESITE` | SameSite | No | `lax` | main | — |

---

## NIM pool / timeouts (defaults safe)

| Variable | Default | Notes |
|----------|---------|-------|
| `NIM_ENDPOINT_POOL_ENABLED` | `true` | Multi-key pool |
| `NIM_ENDPOINT_STRATEGY` | `least_load` | |
| `NIM_ENDPOINT_MAX_CONCURRENT` | `6` | Per endpoint |
| `NIM_ENDPOINT_2/3_API_KEY` (+ base/roles) | empty | Optional peers |
| `NIM_API_KEYS` | `""` | CSV extra keys |
| `NIM_HTTP_TIMEOUT_SEC` | `75` | Must be &lt; map wall |
| `NIM_COMPILE_TIMEOUT_SEC` | `55` | Must be &lt; compile walls |
| `COMPILE_CALL_MAX_SEC` | `180` | Compile wall |
| `MAP_CHUNK_HARD_TIMEOUT_SEC` | `90` | Map wall |
| `JOB_MAX_RUNTIME_SEC` | `1800` | Job watchdog |
| `LLM_PROVIDER` | `openai_compatible` | Ollama only if switched |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Local-only; unused when provider≠ollama |

---

## Optional / feature

| Variable | Purpose | Required | Default |
|----------|---------|----------|---------|
| `ELECTRICITY_MAPS_API_KEY` | Live grid intensity | No | `""` (static fallback) |
| `AWS_*` / `S3_*` | S3 backend | If `OBJECT_STORAGE_BACKEND=s3` | empty |
| Model / QVA / CRE / chunking knobs | Pipeline tuning | No | code defaults |

`GEMINI_API_KEY` in `.env.example` is for **graphify tooling only** — not consumed by FastAPI.

---

## Render Blueprint secrets (`sync: false`)

Must be set in the Render dashboard before first traffic:

1. `DATABASE_URL` (Neon pooled + SSL)
2. `NVIDIA_API_KEY`
3. `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`
4. `CORS_ORIGINS` = `https://<your-app>.vercel.app` (or `*`)

`JWT_SECRET_KEY` is `generateValue: true` in `render.yaml`.
