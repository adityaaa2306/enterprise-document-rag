# Production Deployment Plan — Green Agentic Document Intelligence

**Status:** Phases 0–4 on Render path; Phase 5 = Production Launch & Operational Validation.  
**Constraint:** Phase 1–2 AI architecture is frozen (routing, CRE, understanding, response, retrieval, chunking, validation, explainability).

---

## Approval modifications (locked)

- **Frontend stays Next.js 14** App Router → deploy on **Vercel**. No Vite migration.
- **FastAPI backend kept** — no framework rewrite.
- **ChromaDB kept** — no pgvector.
- **Workers:** prefer simple durable worker first; Redis/Celery/RQ only if required later.
- Implement **one phase at a time**; stop for approval after each.

---

## 1. Current architecture review

| Layer | Current state |
|-------|----------------|
| Frontend | **Next.js 14** App Router + React 18 + Tailwind/Radix (`frontend/`). Not Vite. |
| Backend | **FastAPI + LangGraph + Uvicorn** (`backend/src/api/main.py`). |
| Job execution | `BackgroundTasks` + `threading.Thread` (in-process). |
| Relational DB | SQLAlchemy dual dialect; default **SQLite**; **Alembic** + Postgres support (`src/db/`). |
| Durable state | `jobs`, `conversations`, `conversation_turns`, `routing_events` (recent). |
| Vectors | **ChromaDB** on local `VECTOR_DB_PATH` (not pgvector). |
| Uploads | **Phase 2 done:** object storage (`local` / R2 / S3); Postgres metadata only. Scratch `temp_uploads/` for triage download. |
| Auth | JWT access tokens + bcrypt; **only `/auth/me` protected**; frontend rarely sends Bearer. |
| Cloud config | `backend/render.yaml`; Neon/Render migrate scripts |

| Docker / CI | **No** backend Dockerfile; **no** full compose; **no** GitHub Actions. |
| Observability | Plain logging; `GET /` only; routing telemetry table/JSONL. |

**Target (current):** Next.js→Vercel · FastAPI Docker→**Render** · Neon Postgres · Chroma private service · R2 · JWT+refresh · durable workers · health/ready · compose.

---

## 2. Production readiness score

| Area | Score | Notes |
|------|------:|-------|
| AI agents (Phase 1–2) | 9/10 | Complete — do not touch |
| Postgres + Alembic | 7/10 | Strong foundation |
| Chroma vector path | 4/10 | Local-disk; needs volume strategy |
| Auth end-to-end | 2/10 | JWT present, not enforced |
| Background workers | 2/10 | No real queue/worker |
| Object storage | 0/10 | Missing |
| Docker / Railway | 2/10 | Missing Dockerfile |
| Frontend vs Vite target | N/A | **Cancelled** — keep Next.js 14 on Vercel |
| Health / metrics | 2/10 | Minimal |
| CI/CD | 0/10 | Absent |
| Security (CORS/secrets) | 2/10 | Open CORS; default JWT secret |
| **Overall** | **~32/100** | Demo-deployable ≠ production multi-user |

---

## 3. Every issue preventing production deployment

### P0 — must fix before real users
1. In-process `BackgroundTasks` (no worker / multi-instance).
2. ~~Uploads on local disk only~~ → Phase 2: R2/S3/local object store + metadata columns.
3. Business APIs unauthenticated (`/summarize`, `/rag-query`, `/documents`, …).
4. No Dockerfile / Railway container definition.
5. CORS `allow_origins=["*"]` with credentials.
6. Hardcoded `JWT_SECRET_KEY` default in `config.py`.

### P1 — required for your target architecture
7. No refresh tokens.
8. No `/api/health` or `/api/ready`.
9. Chroma on local disk unsafe for multiple replicas.
10. ~~Frontend is Next.js; target is Vite~~ **Cancelled — keep Next.js on Vercel.**
11. No CI/CD.
12. Frontend does not send `Authorization` on API calls.
13. `user_id` columns unused.

### P2 — hardening / performance
14. No rate limiting.
15. Heavy `torch`/`transformers` cold start.
16. `unstructured[all-docs]` large image.
17. Sync DB sessions only (no async SQLAlchemy).
18. No structured logging / APM.
19. `typescript.ignoreBuildErrors` on frontend.
20. Dual lockfiles / README drift.

---

## 4. Required infrastructure changes

- **Neon** Postgres as production `DATABASE_URL`.
- **Railway**: API service + **worker** service from same image.
- **Persistent volume** (or single-replica policy) for Chroma data dir.
- **Cloudflare R2** (S3-compatible) for PDF/document blobs.
- **Redis** (optional placeholder → required when queue lands).
- **docker-compose.yml**: `api`, `worker`, `postgres`, `chroma`, `redis`.
- **Dockerfile** multi-stage for FastAPI + worker entrypoint.
- Remove reliance on Render-only assumptions for the primary path (keep scripts if useful).

---

## 5. Required backend changes

**Do not change:** CRE, intelligent router, understanding/response agents, retrieval, chunking, QVA, explainability logic.

**Do change:**
- Config: `dev` / `test` / `prod` settings; no secret defaults; CORS origins from env.
- Auth: refresh tokens, bcrypt (keep), protect all data endpoints, stamp `user_id`.
- Storage adapter: upload → R2; Postgres stores `file_url` / `storage_key` only.
- Jobs: enqueue on upload; worker runs LangGraph; progress/result in `jobs` table (already partially there).
- Health: `GET /api/health`, `GET /api/ready` (DB + Chroma path + optional R2).
- Logging: structured JSON logs; basic metrics counters.
- Middleware: secure headers, rate limiting on auth/upload/RAG.
- Alembic-only schema (disable `AUTO_CREATE_SCHEMA` in prod).
- Connection pooling already present — tune for Railway; consider async sessions later (Phase 6+).

---

## 6. Required frontend changes

- **Keep Next.js 14 App Router** (no Vite migration).
- Deploy to **Vercel**; set `NEXT_PUBLIC_API_URL` to Railway API URL.
- Send `Authorization: Bearer …` on API calls (Phase 1).
- Implement refresh-token client flow (Phase 1).
- CORS allow the Vercel domain on the backend.

---

## 7. Required database changes

| Change | Purpose |
|--------|---------|
| Neon as prod URL | Managed Postgres |
| Alembic `002_*` | `documents.file_url`, `storage_key`, `content_type`, `byte_size` |
| Alembic `002_*` | `refresh_tokens` table |
| Enforce `user_id` usage | Multi-tenant isolation |
| Keep out of PG | Embeddings (Chroma), raw PDF bytes |

Existing tables to keep using: users, documents, chunks, jobs, conversations, conversation_turns, routing_events, graph_nodes, graph_edges.

---

## 8. Required deployment changes

| Component | Action |
|-----------|--------|
| Frontend | Vercel (Next.js); env `NEXT_PUBLIC_API_URL` |
| Backend API | Render Web Service (Docker target `api`) |
| Backend worker | Render Background Worker (Docker target `worker`) |
| Migrations | API start / `migrate_render.sh` / `migrate_neon.sh` |
| Secrets | Render + Vercel dashboards only |
| Compose | Local parity for api/worker/postgres/chroma/redis |

---

## 9. Security concerns

- Default JWT secret in source.
- Unauthenticated document/RAG/job access (IDOR).
- Open CORS.
- Tokens in `localStorage` without consistent API use.
- No rate limits → abuse / NIM cost blowups.
- No security headers middleware.
- Large attack surface if upload endpoints stay open.

---

## 10. Performance concerns

- Cold start: torch + HF NLI model.
- Fat image: unstructured + system deps.
- Sync ORM under load.
- Single worker process capacity for LangGraph jobs.
- File-based BM25/embed cache not shared across replicas.
- No Redis for hot conversation/retrieval caching yet.

---

## 11. File-by-file implementation plan

### Phase 0 — Foundation & security baseline
| File | Action |
|------|--------|
| `backend/src/core/config.py` | Remove secret defaults; CORS origins; env tiers hooks |
| `backend/src/core/settings/` (new) | `base.py`, `development.py`, `testing.py`, `production.py` |
| `backend/src/api/main.py` | CORS from env; mount `/api/health`, `/api/ready` |
| `backend/src/api/health.py` (new) | Liveness + readiness checks |
| `backend/.env.example` | Document all vars; no real secrets |
| `backend/src/memory/storage.py` | Ensure prod never uses `create_all` |

### Phase 1 — Auth end-to-end
| File | Action |
|------|--------|
| `backend/src/db/models.py` | `RefreshTokenModel` |
| `backend/alembic/versions/002_*.py` | Migration |
| `backend/src/api/auth.py` | Access + refresh issue/rotate/revoke |
| `backend/src/api/main.py` | `Depends(get_current_user)` on data routes; set `user_id` |
| `backend/src/api/schemas.py` | Token pair schemas |
| Frontend auth pages / API client | Bearer + refresh |

### Phase 2 — Object storage ✅
| File | Action |
|------|--------|
| `backend/src/storage/` | `local` + S3-compatible (R2/S3) adapters |
| `backend/src/db/models.py` | `storage_key`, `file_url`, `original_filename`, `content_type`, `byte_size` |
| Alembic `003_document_object_storage` | Migration |
| `backend/src/api/main.py` | Upload → object store; job downloads scratch for triage |
| `GET /api/ready` | Includes object_storage check |

### Phase 3 — Async workers ✅
| File | Action |
|------|--------|
| `backend/src/worker/` | Poll / claim / process loop (`python -m src.worker`) |
| `backend/src/db/jobs.py` | Enqueue + atomic claim + stale reclaim + heartbeats |
| `backend/src/api/main.py` | Enqueue only (no BackgroundTasks / no AI) |
| Alembic `004_job_queue_worker` | Claim columns + `worker_heartbeats` |
| `backend/docs/PHASE3_DURABLE_WORKER.md` | Architecture + ops |
| **Do not edit** | CRE / router / agents / retrieval / chunking |

### Phase 4 — Docker + Render + Neon ✅
| File | Action |
|------|--------|
| `backend/Dockerfile` | Multi-stage `api` + `worker` |
| `backend/docker-compose.yml` | Local: api, worker, postgres, chroma |
| `backend/render.yaml` | Render blueprint (API + Worker + Chroma) |
| `backend/docs/RENDER_DEPLOYMENT.md` | Deploy guide |
| **Removed** | `railway.toml`, `railway.worker.toml`, `migrate_railway.sh` |
| **Do not edit** | CRE / router / agent business logic |


### Phase 5 — Production Launch & Operational Validation
| File | Action |
|------|--------|
| `frontend/vercel.json` | Next.js Vercel project config |
| `frontend/.env.example` | `NEXT_PUBLIC_API_URL` |
| `backend/docs/PHASE5_PRODUCTION_LAUNCH.md` | URLs, env checklist, smoke, rollback, troubleshooting |
| `backend/scripts/smoke_production.py` | E2E production smoke test |
| `backend/src/api/request_logging.py` | Access logs (`request_id`, status, duration) |
| **Do not edit** | CRE / router / agents / retrieval / chunking |

### Phase 6 — Observability + CI/CD + hardening
| File | Action |
|------|--------|
| Logging middleware | JSON structured logs (beyond Phase 5 access log) |
| Metrics endpoint or exporter | Basic counters |
| Rate limit middleware | Auth/upload/RAG |
| Secure headers middleware | |
| `.github/workflows/backend.yml` | lint, test, docker build |
| `.github/workflows/frontend.yml` | install, build, deploy (Vercel) |

### Explicitly frozen (no edits unless bugfix approved)
- `backend/src/core/cre.py`, `intelligent_router.py`
- `backend/src/agents/*` (except auth/status plumbing if required)
- `backend/src/retrieval/*`, `backend/src/chunking/*`
- Explainability / skills business logic
- Frontend framework migration (Next.js stays)

---

## 12. Estimated implementation phases

| Phase | Name | Est. effort | Depends on |
|------:|------|-------------|------------|
| 0 | Foundation & security baseline | 0.5–1 day | — |
| 1 | Auth end-to-end | 1–2 days | 0 |
| 2 | R2 object storage | 1–2 days | 0–1 |
| 3 | Async workers | 2–3 days | 1–2 |
| 4 | Docker + Render + Neon | 1–2 days | 3 |
| 5 | Next.js on Vercel (no Vite) | 0.5–1 day | 1 |
| 6 | Observability + CI/CD | 1–2 days | 4–5 |

**Total:** ~7–12 working days (Vite migration removed).

**Workers note:** Phase 3 will use a **simple durable worker** (same image / process pool or DB-polled worker). Redis/Celery/RQ only if that cannot meet requirements.

---

## Approval gate

Reply with one of:

1. **Approve Phase 0** — begin foundation & security baseline only.  
2. **Approve plan with changes** — list adjustments (e.g. keep Next.js instead of Vite).  
3. **Hold** — more questions before any code.

After each approved phase: modified files list → tests → summary → **stop** until you approve the next phase.
