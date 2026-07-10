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

    # --- Light tier (chunk summarization) ---
    LIGHT_MODEL_PRIMARY: str = "meta/llama-3.2-3b-instruct"
    LIGHT_MODEL_FALLBACK: str = "google/gemma-2-2b-it"

    # --- Medium tier (escalation on accuracy failure) ---
    MEDIUM_MODEL_PRIMARY: str = "google/gemma-4-31b-it"
    MEDIUM_MODEL_FALLBACK: str = "mistralai/ministral-14b-instruct-2512"

    # --- Heavy tier (final compile + RAG answers) ---
    HEAVY_MODEL_PRIMARY: str = "meta/llama-3.3-70b-instruct"
    HEAVY_MODEL_FALLBACK_1: str = "openai/gpt-oss-120b"
    HEAVY_MODEL_FALLBACK_2: str = "qwen/qwen3.5-122b-a10b"

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

    # --- Phase 2.C ContextAssembler ---
    USE_CONTEXT_ASSEMBLER: bool = True
    CONTEXT_DEDUP_THRESHOLD: float = 0.92
    CONTEXT_TOKEN_BUDGET_LIGHT: int = 2000
    CONTEXT_TOKEN_BUDGET_MEDIUM: int = 4000
    CONTEXT_TOKEN_BUDGET_HEAVY: int = 6000

    # --- Phase 2.D Response Agent ---
    USE_RESPONSE_AGENT: bool = True
    RESPONSE_DEFAULT_SKILL: str = "qa"
    RESPONSE_USE_ROUTING_DECISION: bool = True

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

    # --- Quality Validation Agent ---
    QVA_CONFIDENCE_THRESHOLD: float = 0.60
    QVA_FAITHFULNESS_MIN: float = 0.55
    QVA_HALLUCINATION_MAX: float = 0.15
    QVA_CONTRADICTION_MAX: float = 0.10
    QVA_MAX_ESCALATIONS: int = 1  # exactly +1 tier

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
    WORKER_CLAIM_TIMEOUT_SEC: int = 900  # reclaim processing jobs after this (heartbeat stale)
    WORKER_HEARTBEAT_INTERVAL_SEC: float = 10.0
    WORKER_HEARTBEAT_STALE_SEC: int = 60  # API health: worker considered dead after this
    WORKER_MAX_ATTEMPTS: int = 3
    WORKER_RETRY_BACKOFF_SEC: int = 30
    WORKER_RECLAIM_INTERVAL_SEC: float = 30.0
    # After SIGTERM: finish current job up to this many seconds, then exit
    WORKER_SHUTDOWN_GRACE_SEC: float = 120.0

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
    CHUNK_MAX_TOKENS: int = 512
    CHUNK_SIM_THRESHOLD: float = 0.25  # split when adjacent similarity falls below
    # Optional override; empty → use CHROMA_COLLECTION_NAME
    CHUNK_COLLECTION_NAME: str = ""

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
