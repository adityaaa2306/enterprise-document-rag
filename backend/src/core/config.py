from pydantic_settings import BaseSettings, SettingsConfigDict
import logging
import os
from typing import Optional, List

from src.core.env import normalize_app_env, is_production

# Get the absolute path of the directory where this file is
# e.g., /path/to/project/backend/src/core
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Go up two levels to get the /path/to/project/backend/ directory
# This is where your .env file should be
ENV_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "..", ".env"))

log = logging.getLogger("config")

# Insecure fallback ONLY for local development when JWT_SECRET_KEY is unset.
# Never used when APP_ENV=production.
_DEV_INSECURE_JWT = "dev-only-insecure-jwt-change-me"


class Settings(BaseSettings):
    """
    Loads settings from environment variables and optional backend/.env.

    Tiers via APP_ENV: development | testing | production.
    """

    # --- Runtime environment ---
    APP_ENV: str = "development"
    APP_NAME: str = "Green Agentic API"
    APP_VERSION: str = "4.1.0"

    # --- NVIDIA NIM API ---
    NVIDIA_API_KEY: str = ""
    NVIDIA_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    ELECTRICITY_MAPS_API_KEY: Optional[str] = None
    # Empty zone → resolve via lat/lon (default Pune / IN-WE)
    ELECTRICITY_MAPS_ZONE: str = ""
    ELECTRICITY_MAPS_LAT: float = 18.52
    ELECTRICITY_MAPS_LON: float = 73.85
    # --- Carbon-Aware Region Scheduler (single live region today) ---
    # Modes: single-region (enabled) | carbon-optimized (future multi-region)
    REGION_SCHEDULER_MODE: str = "single-region"
    REGION_SCHEDULER_DEFAULT_REGION: str = "india"
    REGION_SCHEDULER_DEFAULT_REGION_NAME: str = "India"
    REGION_SCHEDULER_PROVIDER: str = "electricity_maps"
    # Per-request HTTP timeout for chat/embeddings (prevents infinite "processing")
    NIM_HTTP_TIMEOUT_SEC: float = 90.0
    # Longer read timeout for final compile (large multi-chunk prompts)
    # Keep compile prompts short-lived — free-tier NIM often stalls on large
    # synthesize calls; fail over (or stitch) instead of hanging the UI.
    NIM_COMPILE_TIMEOUT_SEC: float = 55.0
    # Connect timeout for NIM (separate from read/write)
    NIM_CONNECT_TIMEOUT_SEC: float = 15.0
    # OpenAI SDK transport retries (we also fall back across models ourselves)
    NIM_SDK_MAX_RETRIES: int = 1
    # App-level retries per model for transient NIM errors (timeout/connection/5xx)
    NIM_TRANSIENT_RETRIES: int = 2

    # --- Light tier (chunk summarization) ---
    # llama-3.2-3b timed out 0/4 on NIM free tier (2026-07-13 probe).
    LIGHT_MODEL_PRIMARY: str = "meta/llama-3.1-8b-instruct"
    LIGHT_MODEL_FALLBACK: str = "mistralai/mistral-nemotron"

    # --- Medium tier (escalation on accuracy failure) ---
    # Prefer ministral as primary: gemma-4-31b 0/4 timeouts on NIM free tier (2026-07-13).
    MEDIUM_MODEL_PRIMARY: str = "mistralai/ministral-14b-instruct-2512"
    MEDIUM_MODEL_FALLBACK: str = "meta/llama-3.1-8b-instruct"

    # --- Heavy tier (final compile + RAG answers) ---
    # Prefer ministral: llama-3.3/gpt-oss broken; llama-3.1-70b hangs on large compile.
    HEAVY_MODEL_PRIMARY: str = "mistralai/ministral-14b-instruct-2512"
    HEAVY_MODEL_FALLBACK_1: str = "meta/llama-3.1-70b-instruct"
    HEAVY_MODEL_FALLBACK_2: str = "meta/llama-3.1-8b-instruct"

    # --- Retrieval (embeddings + rerank) ---
    EMBEDDING_MODEL: str = "nvidia/llama-nemotron-embed-1b-v2"
    RERANK_MODEL: str = "nvidia/llama-nemotron-rerank-1b-v2"
    RAG_CANDIDATE_K: int = 20
    RAG_TOP_K: int = 5

    # --- Phase 2.B Hybrid Retrieval + Embedding Cache ---
    ENABLE_HYBRID_RETRIEVAL: bool = True
    ENABLE_EMBEDDING_CACHE: bool = True
    RAG_DENSE_K: int = 20
    RAG_SPARSE_K: int = 20
    RAG_RRF_K: int = 20
    RAG_RERANK_N: int = 20
    ENABLE_PARENT_EXPAND: bool = True
    RAG_PARENT_EXPAND_MAX: int = 3
    # Rerank via NVIDIA retrieval API (circuit-opens on persistent 404)
    ENABLE_RERANK: bool = True
    RERANK_HTTP_TIMEOUT_SEC: float = 8.0

    # --- Phase 2.C ContextAssembler ---
    USE_CONTEXT_ASSEMBLER: bool = True
    CONTEXT_DEDUP_THRESHOLD: float = 0.85
    CONTEXT_TOKEN_BUDGET_LIGHT: int = 2000
    CONTEXT_TOKEN_BUDGET_MEDIUM: int = 4000
    CONTEXT_TOKEN_BUDGET_HEAVY: int = 6000
    # Cap context passed to chat/RAG generation (retrieval unchanged)
    RESPONSE_CONTEXT_BUDGET: int = 2200

    # --- Phase 2.D Response Agent ---
    USE_RESPONSE_AGENT: bool = True
    RESPONSE_DEFAULT_SKILL: str = "qa"
    RESPONSE_USE_ROUTING_DECISION: bool = True
    # Defer explainability until after answer (JSON path) / after stream (SSE)
    RESPONSE_DEFER_EXPLAINABILITY: bool = True

    # --- Phase 2.F Understanding Agent ---
    ENABLE_UNDERSTANDING: bool = True
    UNDERSTANDING_MAX_CHUNKS_PER_CALL: int = 6
    UNDERSTANDING_MAX_TOKENS: int = 2000

    # --- Phase 2.G GraphStore + graph-seeded retrieval ---
    ENABLE_GRAPH_SEED: bool = True
    GRAPH_SEED_MAX_CHUNKS: int = 8
    GRAPH_SEED_MIN_CONFIDENCE: float = 0.4

    # --- Phase 2.H Memory + Explainability ---
    EXPLAINABILITY_ENABLED: bool = True
    CONVERSATION_TTL_HOURS: float = 24.0
    CONVERSATION_MAX_TURNS: int = 40

    # --- Capability Requirement Engine (CRE) ---
    CRE_POLICY_VERSION: str = "cre-v1.0"
    CRE_WEIGHT_REASONING: float = 0.35
    CRE_WEIGHT_STRUCTURAL: float = 0.20
    CRE_WEIGHT_COHERENCE: float = 0.20
    CRE_WEIGHT_RETRIEVAL: float = 0.25
    CRE_HEAVY_COMPILE_CHUNK_THRESHOLD: int = 20

    # --- Final compile resilience ---
    # Soft token budget for a single compile prompt; over this we hierarchical-batch.
    COMPILE_MAX_INPUT_TOKENS: int = 10000
    COMPILE_BATCH_SIZE: int = 8
    # Parallel map summarization workers (NIM-bound; raise for lower wall-clock)
    MAP_MAX_WORKERS: int = 8
    # When API+worker share one process, cap map concurrency so /job-status stays responsive
    EMBEDDED_MAP_MAX_WORKERS: int = 3
    # Parallel intermediate compile batches within one hierarchical round
    COMPILE_MAX_WORKERS: int = 4
    # Parallel QVA chunk validation workers (CPU-bound lexical checks)
    VALIDATE_MAX_WORKERS: int = 8
    # Throttle durable progress DB writes (in-memory always updates)
    PROGRESS_WRITE_INTERVAL_SEC: float = 0.75
    # Prefetch chunk embeddings during map/validate/compile overlap
    ENABLE_EMBED_PREFETCH: bool = True
    # Electricity Maps response cache TTL (seconds)
    ELECTRICITY_MAPS_CACHE_TTL_SEC: float = 300.0

    # --- Quality Validation Agent ---
    QVA_CONFIDENCE_THRESHOLD: float = 0.60
    QVA_FAITHFULNESS_MIN: float = 0.55
    # Lexical "hallucination" flags paraphrases; 0.15 was failing almost all abstractive maps.
    QVA_HALLUCINATION_MAX: float = 0.35
    QVA_CONTRADICTION_MAX: float = 0.10
    # Light→Medium→Heavy ladder: up to 2 escalations (failed chunks only).
    QVA_MAX_ESCALATIONS: int = 2
    # Cap heavy re-summarize so one strict QVA pass cannot escalate every chunk.
    QVA_MAX_ESCALATE_CHUNKS: int = 8
    # Embedding cosine semantic similarity floor (0 disables the check).
    QVA_SEMANTIC_SIM_MIN: float = 0.35
    QVA_ENTITY_RETENTION_MIN: float = 0.40
    # Accept compile when confidence >= this (medium-first compile gate).
    QVA_COMPILE_CONFIDENCE_THRESHOLD: float = 0.58

    # --- Telemetry ---
    ROUTING_TELEMETRY_PATH: str = "./local_db/routing_telemetry.jsonl"
    # Dual-write JSONL even when DB persistence is on (safe rollback / local debug)
    ROUTING_TELEMETRY_JSONL_FALLBACK: bool = True

    # --- Database Configuration ---
    # Local default: SQLite. Production: postgresql://... or postgresql+psycopg://...
    # Aux files (BM25, embed cache, file conversations) — not Chroma embeddings
    VECTOR_DB_PATH: str = "./local_db/aux"
    DATABASE_URL: str = "sqlite:///./agentic_db.sqlite"
    CHROMA_COLLECTION_NAME: str = "documents_nemotron_v2"
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    # When True, skip Alembic and call metadata.create_all (dev convenience only)
    # Forced off when APP_ENV=production (see validate_for_runtime).
    AUTO_CREATE_SCHEMA: bool = False
    # When True, Docker entrypoint runs `alembic upgrade head` before uvicorn
    RUN_MIGRATIONS_ON_STARTUP: bool = False

    # --- Durable runtime state (feature flags — set False to roll back to legacy) ---
    PERSIST_JOBS_TO_DB: bool = True
    PERSIST_CONVERSATIONS_TO_DB: bool = True
    PERSIST_ROUTING_EVENTS_TO_DB: bool = True

    # --- Durable worker (Phase 3) — Postgres/SQLite job queue; no Celery/Redis ---
    WORKER_ID: str = ""  # empty → auto hostname-pid-uuid
    WORKER_POLL_INTERVAL_SEC: float = 2.0
    # Heartbeats refresh ~10s while a job is live; 180s is enough slack for DB
    # contention without leaving restart zombies stuck for 15 minutes.
    WORKER_CLAIM_TIMEOUT_SEC: int = 180
    WORKER_HEARTBEAT_INTERVAL_SEC: float = 10.0
    WORKER_HEARTBEAT_STALE_SEC: int = 60  # API health: worker considered dead after this
    WORKER_MAX_ATTEMPTS: int = 3
    WORKER_RETRY_BACKOFF_SEC: int = 30
    WORKER_RECLAIM_INTERVAL_SEC: float = 30.0
    # After SIGTERM: finish current job up to this many seconds, then exit
    WORKER_SHUTDOWN_GRACE_SEC: float = 120.0
    # Hard wall-clock limit for a single claim attempt (stops orphaned "processing")
    # Large PDFs with medium/heavy tiers + NIM fallbacks need >10 minutes.
    JOB_MAX_RUNTIME_SEC: float = 1800.0
    # Cap a single compile NIM invocation (branch repair / heavy compile).
    # Progress UI polls every 15s inside the wait; without a cap, a hung HTTP
    # client can leave the job at "waiting on model..." indefinitely.
    # 180s ≈ 3 unique models × ~55s compile timeout (+ a little slack).
    COMPILE_CALL_MAX_SEC: float = 180.0
    # Feature extraction LLM/embed probe is optional metadata — never abort the job
    FEATURE_EXTRACTION_OPTIONAL: bool = True
    # When true, API process starts durable worker as an in-process thread
    # (shared NIM/Chroma memory — required for Render free tier).
    RUN_EMBEDDED_WORKER: bool = False

    # --- Chroma vector store (embedded PersistentClient — NOT remote HttpClient) ---
    # Portfolio / single-service: embeddings on local disk under this path.
    # Empty → falls back to VECTOR_DB_PATH for legacy env files.
    CHROMA_PERSIST_DIRECTORY: str = "./local_db/chroma"

    # --- Carbon Scheduler Settings ---
    BASELINE_GRID_INTENSITY: float = 450.0
    LOCAL_GRID_INTENSITY: float = 700.0

    # --- Triage Agent Settings ---
    TRIAGE_STRATEGY: str = "fast"

    # --- Phase 2.A Adaptive Chunking ---
    USE_ADAPTIVE_CHUNKING: bool = True
    # Production structure parser (heading validation → sections → pack).
    # When True, replaces naive Title→parent chunking for map units.
    USE_STRUCTURE_PARSER: bool = True
    HEADING_CONFIDENCE_THRESHOLD: float = 0.55
    STRUCTURE_TARGET_TOKENS: int = 800
    STRUCTURE_MIN_TOKENS: int = 450
    STRUCTURE_MAX_TOKENS: int = 1200
    STRUCTURE_MERGE_SIM_MIN: float = 0.28
    # Target size for each map-summarize unit (legacy ChunkingService path).
    CHUNK_MAX_TOKENS: int = 1500
    # Soft minimum before merging tiny sections together.
    CHUNK_MIN_TOKENS: int = 120
    CHUNK_SIM_THRESHOLD: float = 0.15  # split when adjacent similarity falls below
    # Do not split on low similarity until the buffer is at least this full.
    # Prevents thousands of tiny unstructured elements from each becoming a chunk.
    CHUNK_MIN_TOKENS_BEFORE_SIM_SPLIT: int = 500
    # Soft cap for large docs (500–1000+ pages). Hierarchy handles fan-in;
    # force-cap only when CHUNK_FORCE_CAP is true.
    CHUNK_MAX_COUNT: int = 512
    CHUNK_FORCE_CAP: bool = False
    # Overlap tokens appended from previous chunk when splitting on max size.
    CHUNK_OVERLAP_TOKENS: int = 40
    # Titles open sections; keep False so headings are not summarized alone.
    CHUNK_TITLE_AS_CHUNK: bool = False
    # Optional override; empty → use CHROMA_COLLECTION_NAME
    CHUNK_COLLECTION_NAME: str = ""

    # --- Adaptive hierarchical pipeline ---
    ADAPTIVE_CHUNK_ROUTING: bool = True
    ADAPTIVE_REGIONAL_HIERARCHY: bool = True
    # Medium-first compile; escalate to heavy only if QVA fails.
    COMPILE_MEDIUM_FIRST: bool = True
    # Pipeline intelligence (capability analyzer + strategy selection)
    PIPELINE_INTELLIGENCE_ENABLED: bool = True
    PIPELINE_INTEL_POLICY_VERSION: str = "intel-v1"
    # Carbon budget (routing constraint; does not alter Boundary-A math).
    CARBON_BUDGET_ENABLED: bool = True
    CARBON_BUDGET_G: float = 40.0
    # Naive baseline frontier reference: heavy | gpt-4 | gpt-4o | claude-opus | gpt-o3 | ...
    CARBON_BASELINE_REFERENCE: str = "heavy"
    # Negligible Heavy quality gain vs Medium → prefer Medium (0–1).
    HEAVY_QUALITY_GAIN_MIN: float = 0.02

    # --- Authentication Settings ---
    # Empty by default — production MUST set JWT_SECRET_KEY via env.
    # Development falls back to an insecure placeholder (logged as warning).
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    # Access tokens are short-lived; refresh tokens renew the session.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14
    # When true, also set httpOnly refresh cookie (path=/auth). Body still includes tokens.
    AUTH_COOKIE_ENABLED: bool = False
    AUTH_COOKIE_SECURE: bool = False
    AUTH_COOKIE_SAMESITE: str = "lax"

    # --- Object storage (Phase 2) — PDFs/files; not embeddings ---
    # local | r2 | s3
    OBJECT_STORAGE_BACKEND: str = "local"
    OBJECT_STORAGE_LOCAL_ROOT: str = "./local_db/object_store"
    # Cloudflare R2
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET: str = ""
    R2_ENDPOINT_URL: str = ""  # optional override
    R2_REGION: str = "auto"
    R2_PUBLIC_BASE_URL: str = ""  # optional CDN/public URL prefix
    # AWS S3 fallback
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_S3_BUCKET: str = ""
    AWS_REGION: str = "us-east-1"
    S3_ENDPOINT_URL: str = ""
    S3_PUBLIC_BASE_URL: str = ""

    # --- CORS ---
    # Comma-separated origins, e.g. "http://localhost:3000,https://app.vercel.app"
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"
    # When true AND APP_ENV=development|testing, allow all origins (local DX).
    # Ignored in production.
    CORS_ALLOW_ALL: bool = True

    model_config = SettingsConfigDict(
        env_file=ENV_PATH,
        extra="ignore"
    )

    @property
    def app_env_normalized(self) -> str:
        return normalize_app_env(self.APP_ENV)

    @property
    def is_production(self) -> bool:
        return is_production(self.APP_ENV)

    def resolved_jwt_secret(self) -> str:
        """Return JWT secret; apply insecure dev fallback when appropriate."""
        key = (self.JWT_SECRET_KEY or "").strip()
        if key:
            return key
        if self.is_production:
            raise RuntimeError(
                "JWT_SECRET_KEY must be set when APP_ENV=production"
            )
        log.warning(
            "JWT_SECRET_KEY unset — using insecure development default. "
            "Set JWT_SECRET_KEY before any real deployment."
        )
        return _DEV_INSECURE_JWT

    def cors_allow_origins(self) -> List[str]:
        """Origins list for CORSMiddleware.

        Production: set CORS_ORIGINS to real frontend origin(s), or ``*`` for
        open CORS (disables credentials — fine for Bearer-token SPAs).
        """
        if self.CORS_ALLOW_ALL and not self.is_production:
            return ["*"]
        origins = [
            o.strip()
            for o in (self.CORS_ORIGINS or "").split(",")
            if o.strip()
        ]
        if not origins:
            if self.is_production:
                raise RuntimeError(
                    "CORS_ORIGINS must be set when APP_ENV=production "
                    "(CORS_ALLOW_ALL is ignored in production)."
                )
            return ["http://localhost:3000", "http://127.0.0.1:3000"]
        # Explicit wildcard is allowed in production (credentials auto-disabled).
        if origins == ["*"] or (len(origins) == 1 and origins[0] == "*"):
            return ["*"]
        return origins

    def cors_allow_credentials(self) -> bool:
        # Browsers reject Access-Control-Allow-Origin: * with credentials.
        origins = self.cors_allow_origins()
        if origins == ["*"]:
            return False
        return True

    def light_models(self) -> List[str]:
        return [m for m in [self.LIGHT_MODEL_PRIMARY, self.LIGHT_MODEL_FALLBACK] if m]

    def medium_models(self) -> List[str]:
        return [m for m in [self.MEDIUM_MODEL_PRIMARY, self.MEDIUM_MODEL_FALLBACK] if m]

    def heavy_models(self) -> List[str]:
        return [
            m for m in [
                self.HEAVY_MODEL_PRIMARY,
                self.HEAVY_MODEL_FALLBACK_1,
                self.HEAVY_MODEL_FALLBACK_2,
            ]
            if m
        ]

    def chroma_collection(self) -> str:
        return self.CHUNK_COLLECTION_NAME or self.CHROMA_COLLECTION_NAME

    def effective_map_max_workers(self) -> int:
        """Map concurrency; capped for in-process embedded worker so API polls stay live."""
        base = max(1, int(self.MAP_MAX_WORKERS or 3))
        if bool(self.RUN_EMBEDDED_WORKER):
            cap = max(1, int(getattr(self, "EMBEDDED_MAP_MAX_WORKERS", 3) or 3))
            return min(base, cap)
        return base

    def validate_for_runtime(self, *, require_cors: bool | None = None) -> None:
        """
        Call once at application startup.
        Enforces production safety; soft-warns in development.

        ``require_cors``:
          - True  — enforce CORS_ORIGINS in production (API / HTTP servers)
          - False — skip CORS checks (background worker has no HTTP CORS surface)
          - None  — auto: False when SERVICE_ROLE=worker, else True
        """
        import os

        env = self.app_env_normalized
        log.info(f"APP_ENV={env}")

        # Resolve JWT (raises in production if missing) — required for API and worker
        _ = self.resolved_jwt_secret()

        if require_cors is None:
            role = (os.environ.get("SERVICE_ROLE") or "").strip().lower()
            require_cors = role != "worker"

        if require_cors:
            # CORS (raises in production if misconfigured) — API only
            origins = self.cors_allow_origins()
            log.info(f"CORS origins={origins} credentials={self.cors_allow_credentials()}")
        else:
            log.info("CORS validation skipped (worker process; no HTTP CORS surface)")

        if self.is_production:
            if self.AUTO_CREATE_SCHEMA:
                log.error("AUTO_CREATE_SCHEMA cannot be true in production — forcing False")
                object.__setattr__(self, "AUTO_CREATE_SCHEMA", False)
            if require_cors and self.CORS_ALLOW_ALL:
                log.warning("CORS_ALLOW_ALL is ignored when APP_ENV=production")
            if not (self.NVIDIA_API_KEY or "").strip():
                log.warning("NVIDIA_API_KEY is empty in production — LLM calls will fail")
            persist = (self.CHROMA_PERSIST_DIRECTORY or self.VECTOR_DB_PATH or "").strip()
            log.info("Chroma embedded persist directory=%s", persist or "(default)")


settings = Settings()
