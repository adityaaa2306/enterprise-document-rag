# PostgreSQL Persistence Migration

## Migration plan

### Goals
- PostgreSQL is the **production** relational database.
- SQLite remains fully supported for **local development** via `DATABASE_URL`.
- ChromaDB remains the **vector store** (no pgvector in this phase).
- Durable tables replace transient runtime state: `jobs`, `conversations`, `conversation_turns`, `routing_events`.
- Alembic is the source of truth for schema evolution.
- Single SQLAlchemy `Base` + engine/session factory.
- Existing HTTP APIs unchanged (no frontend changes).
- Feature flags allow safe rollback to legacy in-memory / JSONL / file conversations.

### Phases (this PR)
1. Introduce `src/db/` (base, session, models, jobs/conversations/routing repos).
2. Merge graph models into the shared Base; remove dual engines.
3. Alembic revision `001_prod_persistence`.
4. Wire job/conversation/telemetry writers behind flags (default **on**).
5. Platform migrate scripts + docs.

### Out of scope
- pgvector / moving embeddings into Postgres
- Auth lock-down / multi-tenant API enforcement (columns prepared: `user_id` nullable)
- Business-logic rewrites

---

## Schema diff

### Unchanged (still relational)
| Table | Notes |
|-------|--------|
| `users` | Same; lengths normalized |
| `documents` | + nullable `user_id`, `selected_model`, `crs`, `confidence`, `latency_ms`; `routing_json` / `knowledge_json` → JSON/JSONB |
| `chunks` | Same (+ hierarchy columns if missing) |
| `graph_nodes` / `graph_edges` | Same; now on shared Base |

### New
| Table | Purpose |
|-------|---------|
| `jobs` | Durable job status / result (replaces in-memory `JOB_STATUSES`) |
| `conversations` | Chat sessions with TTL (`expires_at`) |
| `conversation_turns` | Turns for a conversation |
| `routing_events` | Routing telemetry rows (indexed metrics + full JSON event) |

### Not in Postgres
- Chroma embeddings (`VECTOR_DB_PATH`)
- BM25 index files
- Embedding cache files
- Temp uploads

### Indexed metrics (queried often)
On `jobs`, `documents`, `routing_events`: `selected_model`, `crs`, `confidence`, `latency_ms`, and carbon fields where applicable. Full `routing_decision` / `event` stored as JSONB (Postgres) or JSON (SQLite).

---

## ER diagram

```mermaid
erDiagram
    users ||--o{ documents : owns
    users ||--o{ jobs : owns
    users ||--o{ conversations : owns
    users ||--o{ routing_events : "optional"

    documents ||--o{ chunks : contains
    documents ||--o{ graph_nodes : has
    documents ||--o{ graph_edges : has
    documents ||--o{ conversations : "chat about"
    documents ||--o| jobs : "job_id == document_id"

    conversations ||--|{ conversation_turns : has

    users {
        int id PK
        string email UK
        string hashed_password
        string full_name
        bool is_active
        datetime created_at
    }

    documents {
        string id PK
        int user_id FK
        text summary
        float carbon_saved_grams
        float crs
        string selected_model
        json routing_json
        json knowledge_json
    }

    chunks {
        string id PK
        string document_id
        text text
        string parent_id
    }

    jobs {
        string id PK
        int user_id FK
        string status
        float progress
        json result_json
        json routing_decision
        float crs
        string selected_model
        float latency_ms
        float carbon_saved_grams
    }

    conversations {
        string id PK
        int user_id FK
        string document_id
        datetime expires_at
    }

    conversation_turns {
        int id PK
        string conversation_id FK
        string role
        text content
        json entities
    }

    routing_events {
        int id PK
        string job_id
        string selected_model
        float crs
        float confidence
        float latency_ms
        float carbon
        json event
    }

    graph_nodes {
        string id PK
        string document_id
        string node_id
        string name
    }

    graph_edges {
        string id PK
        string document_id
        string src
        string rel
        string dst
        float confidence
    }
```

---

## Feature flags (rollback without schema drop)

| Flag | Default | Legacy behavior when `false` |
|------|---------|------------------------------|
| `PERSIST_JOBS_TO_DB` | `true` | In-memory `JOB_STATUSES` only |
| `PERSIST_CONVERSATIONS_TO_DB` | `true` | JSON files under `VECTOR_DB_PATH/conversations` |
| `PERSIST_ROUTING_EVENTS_TO_DB` | `true` | JSONL only |
| `ROUTING_TELEMETRY_JSONL_FALLBACK` | `true` | Dual-write JSONL even when DB on |
| `AUTO_CREATE_SCHEMA` | `false` | Prefer Alembic; set `true` only for emergency local bootstrap |

---

## How to run migrations

### Local SQLite (default)
```powershell
cd backend
.\scripts\migrate_local.ps1
```

### Local Postgres (Docker)
```bash
cd backend
docker compose -f docker-compose.postgres.yml up -d
export DATABASE_URL=postgresql://green:green@localhost:5432/green_agentic
./scripts/migrate_local.sh
```

### Render / Neon / Supabase
```bash
./scripts/migrate_render.sh
./scripts/migrate_neon.sh
./scripts/migrate_supabase.sh
```
Each requires `DATABASE_URL` pointing at Postgres.

---

## Rollback plan

1. **App-level (preferred, zero downtime):** set flags to `false` and redeploy — APIs keep working with legacy stores.
2. **Schema-level:** `./scripts/rollback_migration.sh` → Alembic `downgrade -1` drops `jobs` / conversations / `routing_events` and additive document metric columns. Does **not** drop users/documents/chunks/graph.
3. **Point `DATABASE_URL` back to SQLite** for local-only rollback.
4. Keep Chroma volume intact either way.

---

## Testing checklist

- [ ] `DATABASE_URL=sqlite:///./agentic_db.sqlite` + `migrate_local` → tables exist; app starts
- [ ] `POST /auth/register` + `/auth/login` work
- [ ] `POST /summarize` → row in `jobs`; poll `/job-status/{id}` survives process restart when DB flag on
- [ ] `/job-result/{id}` returns after complete
- [ ] Document appears in `/documents`; RAG `/rag-query` still uses Chroma
- [ ] `/chat` creates `conversations` + `conversation_turns`
- [ ] `routing_events` gains a row after a job; JSONL still written if fallback on
- [ ] Graph endpoints still work (`/documents/{id}/graph`)
- [ ] Flags off: jobs memory-only; conversations file-based; telemetry JSONL-only
- [ ] Postgres via Docker: same smoke tests
- [ ] `alembic downgrade -1` then upgrade again on a throwaway DB
- [ ] No frontend changes required (existing endpoints/shapes)

---

## Alembic files

| Path | Role |
|------|------|
| `backend/alembic.ini` | Alembic config |
| `backend/alembic/env.py` | Loads `DATABASE_URL` from settings/env |
| `backend/alembic/versions/001_prod_persistence.py` | Initial additive migration |
