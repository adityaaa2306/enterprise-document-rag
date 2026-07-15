# System Architecture

**Green Agentic RAG** — carbon-aware, Owner-scoped document orchestration.

This is the canonical architecture document. Deeper topic docs live under `backend/docs/` and are linked where useful.

```
Browser (Vercel / Next.js)
        │  JWT  or  X-Guest-Session-Id
        ▼
API (Render / FastAPI)  ── Owner resolution ──► Neon (Postgres)
        │                                              │
        │  enqueue job (owner_type + owner_id)         │
        ▼                                              │
Worker (embedded or separate)                          │
        │                                              │
        ├─ Object store (R2) ◄── PDF bytes             │
        ├─ NIM endpoint pool ◄── map / compile / chat  │
        ├─ Frozen DAG execution                        │
        ├─ Summary Ready ──► job.result_json           │
        └─ Background ──► Chroma / BM25 / carbon patch │
```

---

## 1. Identity

### Two entry paths, one Owner

| Path | Credential | Owner |
|------|------------|--------|
| Sign in | Bearer JWT (`users.id`) | `owner_type=user`, `owner_id=str(user_id)` |
| Try Demo | HttpOnly cookie `ga_guest_session` and/or header `X-Guest-Session-Id` | `owner_type=guest`, `owner_id=<uuid>` |

**Priority:** valid JWT wins. Else guest session. Else `401`.

Auth-only surfaces keep `user_id` (register, login, refresh tokens, `/auth/me`).  
Business resources never authorize by `user_id` alone.

```
Owner
 ├── USER   (JWT → users)
 └── GUEST  (guest_sessions)
```

Module: `backend/src/core/owner.py`, `backend/src/api/deps.py` (`get_current_owner`).

---

## 2. Ownership

Every durable business row stamps:

| Column | Meaning |
|--------|---------|
| `owner_type` | `user` \| `guest` |
| `owner_id` | `str(user_id)` or guest session UUID |
| `user_id` | Optional identity FK for authenticated users (null for guests) |

**Tables:** `jobs`, `documents`, `conversations` (+ `guest_sessions` for guest identity).

**Rules:**

- List / aggregate / delete-many → filter **`owner_type` AND `owner_id`**
- Get-by-primary-key → allowed for workers and API, but API **must** `enforce_owner` / `assert_*_for` before returning data
- Guest → user upgrade: **UPDATE ownership in place** (no row copy, no recompute)
- Guest cleanup: Owner-scoped purge; skips sessions with `pending`/`processing` jobs

Detail: `backend/docs/OWNER_ABSTRACTION_FINAL.md`

---

## 3. Pipeline (end-to-end)

```
Upload PDF
  → Object storage (R2) + document/job row
  → Worker claims job
  → Parse / adaptive chunking
  → Feature extraction + CRE routing
  → QVA (quality / validation)
  → Planner freezes DAG
  → Scheduler executes immutable DAG
  → Summary Ready  (result published)
  → Background: embeddings, BM25, carbon finalize, telemetry
  → Search Ready
  → RAG / chat against the same document_id (= job_id)
```

**Invariant:** User and Guest run the **same** pipeline. Only Owner stamps differ. No duplicate guest pipeline or endpoints.

Critical path modules:

| Stage | Module |
|-------|--------|
| API enqueue | `api/main.py` `POST /summarize` |
| Worker | `worker/runner.py` → `orchestrator.agentic_graph` |
| Chunking | `chunking/service.py` |
| Routing (CRE) | `core/intelligent_router.py`, agents feature extraction |
| Plan / freeze | `core/planning.py` |
| Execute DAG | `core/pipeline_executor.py`, `core/dag_scheduler.py` |
| Background | `core/background_services.py` |

Detail: `backend/docs/ORCHESTRATION_THREE_PHASE.md`

---

## 4. Planner

**Role:** Deterministically decide hierarchy topology **before** expensive compile LLMs, then **freeze** the DAG.

```
Adaptive chunks
  → plan hierarchy (regional / chapter / executive as needed)
  → overflow prediction
  → FREEZE DAG  (fingerprint + immutability asserts)
```

After freeze:

- No mid-run topology edits
- No `ensure_prompt_budget` reshapes during execution
- Quality issues → `RepairQueue` (re-run existing node ids only)

Optional levels may be skipped by scale rules (e.g. small docs skip regional/chapter). The execution graph UI shows those as “not required by planner,” not as failures.

Module: `backend/src/core/planning.py`

---

## 5. Scheduler

Two related schedulers:

### Job queue scheduler

- Durable jobs in Postgres (`pending` → `processing` → `complete` \| `error` \| `cancelled`)
- Claim: `FOR UPDATE SKIP LOCKED` (Postgres)
- Heartbeats, stall reclaim, max runtime watchdog
- Portfolio mode: embedded worker (`RUN_EMBEDDED_WORKER=true`) inside the API process

Module: `backend/src/db/jobs.py`, `backend/src/worker/`

### DAG node scheduler

- Executes **frozen** DAG nodes when dependencies complete
- Parallelism bounded by NIM pool capacity and node readiness
- Progress messages keyed by real node kind (chunk / regional / chapter / executive)

Modules: `backend/src/core/dag_scheduler.py`, `pipeline_executor.py`, `pipeline_dag.py`

### Region scheduler (carbon-aware placement)

- Provider-shaped region scheduling; current production mode is **single-region** (configured India / Electricity Maps zone)
- Does not invent fake multi-region hops

Detail: `backend/docs/REGION_SCHEDULER.md`

---

## 6. Carbon

**Reporting Boundary A — operational emissions.**

Single accounting entry: `estimate_workflow_carbon` (`backend/src/carbon/accounting.py`).

```
tokens × J/token × PUE × grid intensity (Electricity Maps)
  → actual_cost_gco2e
  → baseline / saved / efficiency fields on documents + job.result
```

CRE routing prefers lighter models when confidence allows, which feeds the same accounting path.

**UI comparison** (frontier / ChatGPT-style bars) is visualization derived from already-computed `carbon_data` on `/job-result` — it does not change scheduler accounting.

Background phase patches carbon onto the job after Summary Ready when needed.

Detail: `backend/docs/CARBON_ACCOUNTING.md`

---

## 7. Endpoint pool (NVIDIA NIM)

Multi-key / multi-endpoint pool for map, compile, embed, and chat traffic.

```
acquire_endpoint(role) → lease
  → OpenAI-compatible call to integrate.api.nvidia.com (or peer)
release_endpoint → update load / health
```

| Setting | Typical |
|---------|---------|
| `NIM_ENDPOINT_POOL_ENABLED` | `true` |
| `NIM_ENDPOINT_STRATEGY` | `least_load` |
| `NIM_ENDPOINT_MAX_CONCURRENT` | per-endpoint concurrency |
| Extra keys | `NIM_ENDPOINT_2/3_*` or `NIM_API_KEYS` |

Timeouts are layered (HTTP soft, map/compile hard walls, chain time slices for hedged fallback).

Module: `backend/src/agents/nim_endpoint_pool.py`, `agents/models.py`

---

## 8. Background services

Runs **after** Summary Ready so users see the summary without waiting for indexing.

| Step | Work |
|------|------|
| Embeddings | Chunk vectors → Chroma |
| Lexical | BM25 / aux indexes under `VECTOR_DB_PATH` |
| Carbon finalize | Patch `carbon_data` / document meta if deferred |
| Telemetry | Routing events (shared aggregates; not Owner-purged) |
| Metrics | Processing insights / Search Ready flags |

Wiring: `deliver_summary` ends the critical LangGraph path; `store_for_rag` / finalize are invoked from `background_services`, not the summary critical path.

Module: `backend/src/core/background_services.py`

---

## 9. Storage

| Store | What | Production |
|-------|------|------------|
| **Neon Postgres** | Users, jobs, documents, conversations, guest_sessions, routing_events | Required (`DATABASE_URL`); SQLite rejected when `APP_ENV=production` |
| **Cloudflare R2** | Uploaded PDFs (`documents/{owner_type}/{owner_id}/…`) | `OBJECT_STORAGE_BACKEND=r2` |
| **Chroma** | Embeddings | Embedded PersistentClient on `/data/chroma` (portfolio); HttpClient-ready |
| **Aux FS** | BM25, caches, telemetry JSONL | `/data/aux` on Render disk |
| **In-memory job cache** | Hot path progress | Always backed by DB when `PERSIST_JOBS_TO_DB=true` |

Schema changes via **Alembic** (`RUN_MIGRATIONS_ON_STARTUP` on Render). Guest Owner columns: migration `006_guest_owner`.

Modules: `db/`, `memory/storage.py`, `storage/factory.py`

---

## 10. Guest mode

Same product surface without login.

```
Landing → Try Demo → guest session
  → Upload → Summary Ready → Search Ready → Chat
  → 2h inactivity (sliding on every Owner API call)
  → Sign in → optional ownership transfer
  → or expire → Owner-scoped cleanup
```

| Limit | Value |
|-------|-------|
| Active documents | 1 (retain-latest) |
| PDF size | 25 MB |
| Chats / session | 50 |
| Inactivity | 2 hours (sliding) |

Cross-origin (Vercel → Render): send `X-Guest-Session-Id` (cookie alone fails under `CORS_ORIGINS=*` / `SameSite=Lax`).

Docs: `GUEST_MODE_ARCHITECTURE.md`, `GUEST_MODE_LIFECYCLE.md`, `GUEST_MODE_SECURITY.md`

---

## 11. Deployment

| Layer | Platform |
|-------|----------|
| Frontend | Vercel (Next.js) — `NEXT_PUBLIC_API_URL` |
| API + embedded worker | Render |
| Database | Neon Postgres |
| Objects | Cloudflare R2 |
| LLM | NVIDIA NIM |
| Vectors | Chroma on Render disk (`/data`) |

Startup fails fast in production if Postgres, JWT, NIM keys, or R2 (when configured) are missing — `Settings.validate_for_runtime()`.

```
Vercel  ──HTTPS──►  Render API :PORT
                       │
                       ├─ Neon
                       ├─ R2
                       ├─ NIM
                       └─ /data (Chroma + aux)
```

Docs: `DEPLOYMENT_ENVIRONMENT.md`, `PRODUCTION_DEPLOYMENT_CHECKLIST.md`, `RENDER_DEPLOYMENT.md`

---

## 12. Frontend surface

| Route / UI | Role |
|------------|------|
| Landing | Brand + **Try Demo** / **Sign In** |
| `/new-job` | Upload + preference |
| `/results` | Poll status → summary, carbon, execution graph, chat |
| Dashboard | Owner-scoped jobs, documents, carbon stats |
| Guest badge | Inactivity remaining + upgrade CTA |

API client (`frontend/lib/api.ts`) attaches Bearer **or** guest header; guests are not bounced to login on `401` when a guest session exists.

---

## 13. Primary API map

| Method | Path | Notes |
|--------|------|-------|
| POST | `/auth/register`, `/auth/login`, `/auth/refresh` | JWT |
| POST/GET | `/guest/session` | Create / resume / badge |
| POST | `/guest/upgrade` | Transfer guest → user |
| POST | `/summarize` | Enqueue (Owner-stamped) |
| GET | `/job-status/{id}`, `/job-result/{id}`, `/job-events/{id}` | Owner-checked |
| POST | `/jobs/{id}/cancel` | Owner-checked |
| POST | `/rag-query`, `/rag-query/stream`, `/chat` | Owner-checked |
| GET | `/documents`, `/dashboard-stats` | Owner-filtered |
| GET | `/health`, `/api/ready` | Ops |

---

## 14. Mental model (one paragraph)

An **Owner** (user or guest) uploads a PDF into **R2**; the API enqueues a durable **job** in **Neon**. A **worker** downloads the file, **chunks** it, **routes** chunks with CRE, **plans and freezes** a DAG, then **schedules** NIM work through the **endpoint pool** until **Summary Ready**. **Background services** index for RAG and finalize **Boundary A carbon**. The same Owner chats and searches without a second pipeline. Guests expire after **2h inactivity** (or upgrade by transferring Owner stamps). Production runs on **Vercel + Render + Neon + R2 + NIM**.

---

## Related documents

| Doc | Scope |
|-----|--------|
| `backend/docs/ORCHESTRATION_THREE_PHASE.md` | Planning / frozen DAG / background |
| `backend/docs/OWNER_ABSTRACTION_FINAL.md` | Ownership enforcement |
| `backend/docs/GUEST_MODE_*.md` | Guest lifecycle & security |
| `backend/docs/CARBON_ACCOUNTING.md` | Boundary A methodology |
| `backend/docs/REGION_SCHEDULER.md` | Region placement |
| `backend/docs/DEPLOYMENT_ENVIRONMENT.md` | Env vars |
| `backend/docs/PRODUCTION_DEPLOYMENT_CHECKLIST.md` | Ship checklist |
| `README.md` | Install & runbook |
