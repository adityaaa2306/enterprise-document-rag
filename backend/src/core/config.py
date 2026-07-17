from pydantic_settings import BaseSettings, SettingsConfigDict
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

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

# Model fields we always dump at startup / before executive compile.
_RESOLVED_MODEL_FIELDS: Tuple[str, ...] = (
    "MEDIUM_MODEL_PRIMARY",
    "MEDIUM_MODEL_FALLBACK",
    "HEAVY_MODEL_PRIMARY",
    "HEAVY_MODEL_FALLBACK_1",
    "HEAVY_MODEL_FALLBACK_2",
)


def _env_file_defines(name: str) -> bool:
    """True if backend/.env contains an assignment for ``name`` (uncommented)."""
    path = ENV_PATH
    if not path or not os.path.isfile(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[7:].strip()
                key, _, _val = line.partition("=")
                if key.strip() == name:
                    return True
    except OSError:
        return False
    return False


def resolve_model_setting_source(settings_obj: "Settings", field: str) -> str:
    """
    Report where a Settings field's resolved value came from.

    - process_environment: os.environ has the key (wins over .env for pydantic)
    - env_file: key present in backend/.env (or marked set without os.environ)
    - class_default: not provided by env; pydantic used the class Field default
    """
    if field in os.environ:
        return "process_environment"
    if _env_file_defines(field):
        return "env_file"
    # pydantic-settings marks non-default sources in model_fields_set
    try:
        if field in settings_obj.model_fields_set:
            return "environment"
    except Exception:
        pass
    return "class_default"


def log_resolved_llm_model_config(
    settings_obj: "Settings",
    *,
    phase: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Log fully resolved medium/heavy model ids + provenance for the running process.
    Returns the payload for tests / callers. Does not invent values — reads settings_obj.
    """
    rows: Dict[str, Any] = {}
    for field in _RESOLVED_MODEL_FIELDS:
        value = getattr(settings_obj, field, None)
        source = resolve_model_setting_source(settings_obj, field)
        rows[field] = {"value": value, "source": source}
        log.info(
            "RESOLVED_LLM_MODEL_CONFIG phase=%s %s=%r source=%s",
            phase,
            field,
            value,
            source,
        )
    medium_chain = list(settings_obj.medium_models())
    heavy_chain = list(settings_obj.heavy_models())
    log.info(
        "RESOLVED_LLM_MODEL_CONFIG phase=%s medium_models()=%s heavy_models()=%s env_file=%s",
        phase,
        medium_chain,
        heavy_chain,
        ENV_PATH,
    )
    if extra:
        log.info(
            "RESOLVED_LLM_MODEL_CONFIG phase=%s extra=%s",
            phase,
            extra,
        )
    payload = {
        "phase": phase,
        "fields": rows,
        "medium_models": medium_chain,
        "heavy_models": heavy_chain,
        "env_file": ENV_PATH,
        "extra": extra or {},
    }
    return payload


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
    # Optional multi-endpoint NIM pool (least-load). Endpoint 1 = NVIDIA_API_KEY.
    NIM_ENDPOINT_POOL_ENABLED: bool = True
    NIM_ENDPOINT_STRATEGY: str = "least_load"  # least_load | round_robin
    NIM_ENDPOINT_COOLDOWN_SEC: float = 8.0
    NIM_ENDPOINT_RATELIMIT_COOLDOWN_SEC: float = 20.0
    # Hard cap of in-flight HTTP calls per endpoint (capacity-aware scheduler).
    # Prefer per-endpoint NIM_ENDPOINT_{i}_MAX_CONCURRENT when set.
    NIM_ENDPOINT_MAX_CONCURRENT: int = 6
    NIM_ENDPOINT_1_MAX_CONCURRENT: Optional[int] = None
    NIM_ENDPOINT_2_MAX_CONCURRENT: Optional[int] = None
    NIM_ENDPOINT_3_MAX_CONCURRENT: Optional[int] = None
    NIM_ENDPOINT_4_MAX_CONCURRENT: Optional[int] = None
    NIM_ENDPOINT_5_MAX_CONCURRENT: Optional[int] = None
    # How long a worker waits for an endpoint slot before re-queueing.
    NIM_ENDPOINT_ACQUIRE_TIMEOUT_SEC: float = 120.0
    NIM_ENDPOINT_1_ROLES: str = "map,compile,embed,any"
    NIM_ENDPOINT_2_API_KEY: str = ""
    NIM_ENDPOINT_2_BASE_URL: str = ""
    NIM_ENDPOINT_2_ROLES: str = "map,compile,embed,any"
    NIM_ENDPOINT_3_API_KEY: str = ""
    NIM_ENDPOINT_3_BASE_URL: str = ""
    NIM_ENDPOINT_3_ROLES: str = "map,compile,embed,any"
    # Comma-separated extra keys (same BASE_URL as primary)
    NIM_API_KEYS: str = ""
    # Optional workload split: set endpoint-3 roles to "compile" only, etc.
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
    # Soft TTFT: if no first token by this deadline, cancel and try another endpoint.
    NIM_SOFT_TTFT_TIMEOUT_SEC: float = 45.0
    # Interactive RAG stream path — fail over faster than map/compile so Chat
    # does not sit on "Thinking…" for a full NIM_HTTP_TIMEOUT on a hung primary.
    NIM_RAG_SOFT_TTFT_TIMEOUT_SEC: float = 18.0
    # Hard per-call HTTP read — MUST be strictly below MAP_CHUNK_HARD_TIMEOUT_SEC
    # so hung NIM sockets abort before the node wrapper wall.
    NIM_HARD_TIMEOUT_SEC: float = 75.0
    # Per-request HTTP timeout for chat/embeddings (connect+read on the client).
    NIM_HTTP_TIMEOUT_SEC: float = 75.0
    # Per-chunk scheduler hard abort (wrapper wall above HTTP).
    MAP_CHUNK_HARD_TIMEOUT_SEC: float = 90.0
    # Pull-based capacity scheduler for map/escalate (vs submit-all ThreadPool).
    CAPACITY_SCHEDULER_ENABLED: bool = True
    # Retry empty map summaries before QVA (endpoint/model rotate inside call).
    MAP_EMPTY_RETRY_ATTEMPTS: int = 2
    # Longer read timeout for final compile (large multi-chunk prompts)
    # Keep compile prompts short-lived — free-tier NIM often stalls on large
    # synthesize calls; fail over (or stitch) instead of hanging the UI.
    NIM_COMPILE_TIMEOUT_SEC: float = 55.0
    # Connect timeout for NIM (separate from read/write)
    NIM_CONNECT_TIMEOUT_SEC: float = 15.0
    # OpenAI SDK transport retries (we also fall back across models ourselves)
    NIM_SDK_MAX_RETRIES: int = 1
    # App-level retries per model for transient NIM errors (timeout/connection/5xx)
    # Keep low: prefer rotating endpoints over long same-model waits.
    NIM_TRANSIENT_RETRIES: int = 1
    # Same-model retries across different endpoints before model fallback.
    NIM_ENDPOINT_RETRIES_PER_MODEL: int = 2
    # Global NIM request throttle (token bucket shared by all workers/stages).
    NIM_RATE_LIMITER_ENABLED: bool = True
    # Token-bucket ceiling across all endpoints. Sized for multi-key pools;
    # genuine 429s still trigger backoff via RateLimitBackpressure.
    NIM_MAX_REQUESTS_PER_MINUTE: float = 180.0
    # Backoff when 429 / RateLimitBackpressure is requeued at the pool.
    NIM_RATE_LIMIT_BASE_BACKOFF_SEC: float = 1.5
    NIM_RATE_LIMIT_MAX_BACKOFF_SEC: float = 45.0
    # Extra requeue budget for rate-limit backpressure (vs empty-summary retries).
    NIM_RATE_LIMIT_MAX_REQUEUES: int = 8

    # --- Fallback-chain time slices (shared wall → per-model budgets) ---
    # Prevents the primary from consuming the entire MAP/COMPILE wall and
    # starving designated fallbacks. Fractions are position weights (renormalized).
    CHAIN_SLICE_ENABLED: bool = True
    MAP_CHAIN_SLICE_FRACTIONS: str = "0.45,0.35,0.20"
    COMPILE_CHAIN_SLICE_FRACTIONS: str = "0.40,0.35,0.25"
    CHAIN_SLICE_MIN_SEC: float = 8.0
    # Compile-only: if primary has not returned by its slice, fire the next
    # fallback concurrently and take the first success. Trades extra API
    # cost/carbon for better odds of a true executive summary vs stitch.
    # Carbon/cost tradeoff: up to ~2× compile NIM spend when hedge fires.
    COMPILE_HEDGED_FALLBACK_ENABLED: bool = True
    # Rolling reliability window for soft deprioritization (never hard-ban).
    MODEL_RELIABILITY_WINDOW: int = 50
    MODEL_RELIABILITY_SOFT_DEPRIORITIZE: bool = False
    MODEL_RELIABILITY_TIMEOUT_RATE_THRESHOLD: float = 0.55
    MODEL_RELIABILITY_MIN_SAMPLES: int = 20

    # --- Light tier (chunk summarization) ---
    # llama-3.2-3b timed out 0/4 on NIM free tier (2026-07-13 probe).
    LIGHT_MODEL_PRIMARY: str = "meta/llama-3.1-8b-instruct"
    LIGHT_MODEL_FALLBACK: str = "mistralai/mistral-nemotron"

    # --- Medium tier (escalation on accuracy failure) ---
    # Prefer ministral as primary: gemma-4-31b 0/4 timeouts on NIM free tier (2026-07-13).
    MEDIUM_MODEL_PRIMARY: str = "mistralai/ministral-14b-instruct-2512"
    MEDIUM_MODEL_FALLBACK: str = "meta/llama-3.1-8b-instruct"

    # --- Heavy tier (final compile + RAG answers) ---
    HEAVY_MODEL_PRIMARY: str = "meta/llama-3.3-70b-instruct"
    HEAVY_MODEL_FALLBACK_1: str = "openai/gpt-oss-120b"
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
    # Parallel map summarization workers — hard-capped by endpoint capacity
    # (nim_endpoint_count × NIM_ENDPOINT_MAX_CONCURRENT) in effective_map_max_workers().
    MAP_MAX_WORKERS: int = 12
    # Unified pool size for map + compile DAG nodes (Task 2). Map/compile
    # effective_* helpers prefer this when set.
    MAX_PARALLEL_WORKERS: int = 12
    # When API+worker share one process, cap map concurrency so /job-status stays responsive.
    # Keep high enough to saturate a multi-endpoint NIM pool (was 3–4 → severe queueing).
    EMBEDDED_MAP_MAX_WORKERS: int = 12
    # Parallel DAG / hierarchical compile node workers (also capacity-capped)
    COMPILE_MAX_WORKERS: int = 6
    # Per-node hard timeout (cancel/reassign one node without stalling siblings)
    COMPILE_NODE_HARD_TIMEOUT_SEC: float = 90.0
    # Wall-clock reserved exclusively for the executive compile stage when the
    # job starts. Map / regional / chapter / escalate / accounting must not
    # consume this tail; executive compile always receives a fresh reserved
    # window (capped by the absolute job deadline). Does not raise JOB_MAX_RUNTIME.
    COMPILE_RESERVED_SEC: float = 60.0
    # LLM provider: openai_compatible (NIM) | ollama
    LLM_PROVIDER: str = "openai_compatible"
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"
    OLLAMA_TIMEOUT_SEC: float = 120.0
    # Parallel QVA chunk validation workers (CPU-bound lexical checks)
    VALIDATE_MAX_WORKERS: int = 8
    # DAG hierarchical compile (parallel regional/chapter/executive nodes)
    DAG_COMPILE_ENABLED: bool = True
    # One continuous DAG executor owns map→QVA escalate→compile (LangGraph thin).
    UNIFIED_DAG_EXECUTOR_ENABLED: bool = True
    # Soft context window used for 80% prompt-size gating in DAG compile
    COMPILE_CONTEXT_WINDOW_TOKENS: int = 12000
    COMPILE_PROMPT_MAX_CONTEXT_FRAC: float = 0.80
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
    # Shared across the whole fallback chain (primary + fallbacks), not per model.
    # Must be strictly greater than NIM_COMPILE_TIMEOUT_SEC (asserted at startup).
    COMPILE_CALL_MAX_SEC: float = 180.0
    # Cumulative wall-clock ceiling for the entire reduce_compile node
    # (medium + QVA + heavy + branch repair + global recompile). When exhausted,
    # skip remaining long NIM calls and fall through to stitched fallback.
    REDUCE_COMPILE_MAX_SEC: float = 270.0
    # Job heartbeat older than this while status=processing → stalled (requeue).
    # Default ≈ 2× WORKER_HEARTBEAT_INTERVAL_SEC so a dead worker is visible
    # well before JOB_MAX_RUNTIME_SEC.
    WORKER_JOB_HEARTBEAT_STALE_SEC: float = 25.0
    # Build BM25 off the critical store_for_rag path (Chroma upsert still sync).
    BM25_ASYNC_BUILD: bool = True
    # Feature extraction LLM/embed probe is optional metadata — never abort the job
    FEATURE_EXTRACTION_OPTIONAL: bool = True
    # Soft wall for optional LLM document classifier (heuristic fallback on timeout).
    FEATURE_EXTRACTION_LLM_TIMEOUT_SEC: float = 12.0
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
    # Soft advisory only — do not block 1200+ page docs unless FORCE_CAP.
    CHUNK_MAX_COUNT: int = 4096
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
    # Never expose JWT_SECRET_KEY (or any server secret) to the frontend.
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    # Access tokens are short-lived; refresh tokens renew the session.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14
    # bcrypt work factor for new password hashes (existing hashes keep their cost).
    BCRYPT_ROUNDS: int = 12
    # Auth endpoint rate limits (per IP sliding window).
    AUTH_LOGIN_RATE_LIMIT: int = 10
    AUTH_LOGIN_RATE_WINDOW_SEC: float = 900.0
    AUTH_REGISTER_RATE_LIMIT: int = 5
    AUTH_REGISTER_RATE_WINDOW_SEC: float = 3600.0
    AUTH_REFRESH_RATE_LIMIT: int = 60
    AUTH_REFRESH_RATE_WINDOW_SEC: float = 900.0
    AUTH_GUEST_RATE_LIMIT: int = 30
    AUTH_GUEST_RATE_WINDOW_SEC: float = 3600.0
    # Coarse per-IP auth middleware cap (handlers enforce tighter action limits).
    AUTH_IP_RATE_LIMIT: int = 40
    AUTH_IP_RATE_WINDOW_SEC: float = 60.0
    # --- Abuse protection (API / AI / scrape) ---
    ABUSE_PROTECTION_ENABLED: bool = True
    API_RATE_LIMIT: int = 120
    API_RATE_WINDOW_SEC: float = 60.0
    AI_RATE_LIMIT: int = 20
    AI_RATE_WINDOW_SEC: float = 60.0
    AI_RATE_LIMIT_GUEST: int = 10
    SCRAPE_RATE_LIMIT: int = 60
    SCRAPE_RATE_WINDOW_SEC: float = 60.0
    ABUSE_BLOCK_EMPTY_USER_AGENT: bool = True
    ABUSE_BLOCK_BOT_USER_AGENTS: bool = True
    ABUSE_BOT_LIMIT_FACTOR: float = 0.25
    ABUSE_LOG_BOT_CLIENTS: bool = True
    # When true, also set httpOnly refresh cookie (path=/auth).
    AUTH_COOKIE_ENABLED: bool = False
    AUTH_COOKIE_SECURE: bool = False
    AUTH_COOKIE_SAMESITE: str = "lax"
    # Cross-origin SPAs need refresh in JSON; set false when cookie-only.
    AUTH_RETURN_REFRESH_IN_BODY: bool = True
    # HTTPS / transport security (None = enforce automatically when APP_ENV=production)
    FORCE_HTTPS: Optional[bool] = None
    TRUST_PROXY_HEADERS: bool = True  # honor X-Forwarded-Proto from Render/Vercel
    HSTS_MAX_AGE_SEC: int = 31536000
    # Comma-separated hosts for TrustedHostMiddleware; empty = disabled
    TRUSTED_HOSTS: str = ""
    # Require TLS on DATABASE_URL for non-private hosts in production
    DATABASE_REQUIRE_SSL: bool = True

    # --- Uploads (HTTP /summarize) ---
    # Hard cap for authenticated users (guests use GUEST_MAX_PDF_BYTES = 25 MiB).
    MAX_UPLOAD_BYTES: int = 50 * 1024 * 1024

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
            if self.is_production and len(key) < 32:
                raise RuntimeError(
                    "JWT_SECRET_KEY must be at least 32 characters in production"
                )
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

    def nim_endpoint_count(self) -> int:
        """How many NIM API keys are configured (primary + peers + CSV)."""
        n = 1 if (self.NVIDIA_API_KEY or "").strip() else 0
        for i in (2, 3, 4, 5):
            if (getattr(self, f"NIM_ENDPOINT_{i}_API_KEY", None) or "").strip():
                n += 1
        csv = (self.NIM_API_KEYS or "").strip()
        if csv:
            for key in csv.split(","):
                if key.strip() and key.strip() != (self.NVIDIA_API_KEY or "").strip():
                    n += 1
        return n

    def _per_endpoint_max_concurrent(self, index: int) -> int:
        raw = getattr(self, f"NIM_ENDPOINT_{index}_MAX_CONCURRENT", None)
        if raw is not None:
            try:
                return max(1, int(raw))
            except (TypeError, ValueError):
                pass
        return max(1, int(self.NIM_ENDPOINT_MAX_CONCURRENT or 6))

    def effective_nim_capacity(self) -> int:
        """Sum of per-endpoint max_concurrent across configured NIM keys."""
        if not bool(getattr(self, "NIM_ENDPOINT_POOL_ENABLED", True)):
            return self._per_endpoint_max_concurrent(1)
        total = 0
        default_per = max(1, int(self.NIM_ENDPOINT_MAX_CONCURRENT or 6))
        if (self.NVIDIA_API_KEY or "").strip():
            total += self._per_endpoint_max_concurrent(1)
        for i in (2, 3, 4, 5):
            if (getattr(self, f"NIM_ENDPOINT_{i}_API_KEY", None) or "").strip():
                total += self._per_endpoint_max_concurrent(i)
        csv = (self.NIM_API_KEYS or "").strip()
        if csv:
            for key in csv.split(","):
                k = key.strip()
                if k and k != (self.NVIDIA_API_KEY or "").strip():
                    total += default_per
        return max(1, total or default_per)

    def effective_parallel_workers(self) -> int:
        """Unified MAX_PARALLEL_WORKERS capped by NIM endpoint capacity."""
        base = max(1, int(getattr(self, "MAX_PARALLEL_WORKERS", None) or self.MAP_MAX_WORKERS or 8))
        capacity = self.effective_nim_capacity()
        scaled = min(base, capacity)
        if bool(self.RUN_EMBEDDED_WORKER):
            cap = max(1, int(getattr(self, "EMBEDDED_MAP_MAX_WORKERS", 12) or 12))
            return min(scaled, cap)
        return scaled

    def effective_map_max_workers(self) -> int:
        """Map concurrency ≤ endpoint capacity (never overload NIM)."""
        return self.effective_parallel_workers()

    def effective_compile_max_workers(self) -> int:
        """Compile workers: COMPILE_MAX_WORKERS capped by NIM capacity."""
        base = max(1, int(getattr(self, "COMPILE_MAX_WORKERS", None) or 6))
        capacity = self.effective_nim_capacity()
        scaled = min(base, capacity)
        if bool(self.RUN_EMBEDDED_WORKER):
            cap = max(1, int(getattr(self, "EMBEDDED_MAP_MAX_WORKERS", 12) or 12))
            return min(scaled, cap)
        return scaled

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

        # Timeout invariants: HTTP connect+read must abort before every node
        # wrapper wall, otherwise ThreadPoolExecutor "timeouts" never release.
        compile_read = float(self.NIM_COMPILE_TIMEOUT_SEC or 0.0)
        compile_connect = float(self.NIM_CONNECT_TIMEOUT_SEC or 0.0)
        compile_wall = float(self.COMPILE_CALL_MAX_SEC or 0.0)
        map_http = float(self.NIM_HTTP_TIMEOUT_SEC or 0.0)
        map_hard = float(self.NIM_HARD_TIMEOUT_SEC or map_http or 0.0)
        map_wall = float(self.MAP_CHUNK_HARD_TIMEOUT_SEC or 0.0)
        node_wall = float(self.COMPILE_NODE_HARD_TIMEOUT_SEC or 0.0)
        reserved = float(self.COMPILE_RESERVED_SEC or 0.0)
        if reserved <= 0:
            raise ValueError("COMPILE_RESERVED_SEC must be positive")
        if node_wall > 0 and reserved > node_wall:
            log.warning(
                "COMPILE_RESERVED_SEC (%.0f) > COMPILE_NODE_HARD_TIMEOUT_SEC (%.0f); "
                "clamping reserved to node wall",
                reserved,
                node_wall,
            )
            object.__setattr__(self, "COMPILE_RESERVED_SEC", node_wall)
            reserved = node_wall
        if compile_read <= 0 or compile_wall <= 0:
            raise ValueError(
                "NIM_COMPILE_TIMEOUT_SEC and COMPILE_CALL_MAX_SEC must be positive"
            )
        if compile_read >= compile_wall:
            raise ValueError(
                f"NIM_COMPILE_TIMEOUT_SEC ({compile_read}) must be strictly less than "
                f"COMPILE_CALL_MAX_SEC ({compile_wall}) so the HTTP client can abort "
                f"before the compile wall fires"
            )
        if compile_connect >= compile_wall:
            raise ValueError(
                f"NIM_CONNECT_TIMEOUT_SEC ({compile_connect}) must be strictly less than "
                f"COMPILE_CALL_MAX_SEC ({compile_wall})"
            )
        if map_http <= 0 or map_wall <= 0:
            raise ValueError(
                "NIM_HTTP_TIMEOUT_SEC and MAP_CHUNK_HARD_TIMEOUT_SEC must be positive"
            )
        # Auto-heal timeout ladders so a bad Render/dashboard env cannot brick deploy.
        # HTTP/hard must abort *before* the map node wall, else ThreadPool "timeouts"
        # never release hung sockets.
        desired_http = min(map_http, map_hard) if map_hard > 0 else map_http
        if desired_http >= map_wall or map_hard >= map_wall:
            healed_http = max(5.0, map_wall - 15.0)
            healed_hard = max(5.0, map_wall - 15.0)
            log.warning(
                "Timeout ladder invalid "
                "(NIM_HTTP_TIMEOUT_SEC=%s NIM_HARD_TIMEOUT_SEC=%s "
                "MAP_CHUNK_HARD_TIMEOUT_SEC=%s); clamping HTTP/HARD to %.0f",
                map_http,
                map_hard,
                map_wall,
                healed_http,
            )
            object.__setattr__(self, "NIM_HTTP_TIMEOUT_SEC", healed_http)
            object.__setattr__(self, "NIM_HARD_TIMEOUT_SEC", healed_hard)
            map_http = healed_http
            map_hard = healed_hard
        if compile_connect >= map_wall:
            healed_connect = max(1.0, min(float(compile_connect), map_wall - 1.0))
            log.warning(
                "NIM_CONNECT_TIMEOUT_SEC (%.0f) >= MAP_CHUNK_HARD_TIMEOUT_SEC (%.0f); "
                "clamping connect to %.0f",
                compile_connect,
                map_wall,
                healed_connect,
            )
            object.__setattr__(self, "NIM_CONNECT_TIMEOUT_SEC", healed_connect)
        if node_wall > 0 and compile_read >= node_wall:
            raise ValueError(
                f"NIM_COMPILE_TIMEOUT_SEC ({compile_read}) must be strictly less than "
                f"COMPILE_NODE_HARD_TIMEOUT_SEC ({node_wall})"
            )
        reduce_wall = float(self.REDUCE_COMPILE_MAX_SEC or 0.0)
        if reduce_wall < compile_wall:
            log.warning(
                "REDUCE_COMPILE_MAX_SEC (%.0f) < COMPILE_CALL_MAX_SEC (%.0f); "
                "raising REDUCE_COMPILE_MAX_SEC to match",
                reduce_wall,
                compile_wall,
            )
            object.__setattr__(self, "REDUCE_COMPILE_MAX_SEC", compile_wall)

        if self.is_production:
            if self.AUTO_CREATE_SCHEMA:
                log.error("AUTO_CREATE_SCHEMA cannot be true in production — forcing False")
                object.__setattr__(self, "AUTO_CREATE_SCHEMA", False)
            if require_cors and self.CORS_ALLOW_ALL:
                log.warning("CORS_ALLOW_ALL is ignored when APP_ENV=production")

            # --- Hard production requirements (fail fast at startup) ---
            db_url = (self.DATABASE_URL or "").strip().lower()
            if not db_url or db_url.startswith("sqlite"):
                raise RuntimeError(
                    "DATABASE_URL must be a Postgres URL when APP_ENV=production "
                    "(SQLite is not durable on Render's ephemeral filesystem). "
                    "Set DATABASE_URL=postgresql+psycopg://… (Neon pooled recommended)."
                )
            if bool(getattr(self, "DATABASE_REQUIRE_SSL", True)):
                from src.api.security_middleware import (
                    validate_database_url_for_public_exposure,
                )

                validate_database_url_for_public_exposure(self.DATABASE_URL)

            jwt_key = (self.JWT_SECRET_KEY or "").strip().lower()
            if any(
                bad in jwt_key
                for bad in (
                    "change-me",
                    "dev-only",
                    "insecure",
                    "your-secret",
                    "placeholder",
                )
            ):
                raise RuntimeError(
                    "JWT_SECRET_KEY looks like a placeholder — set a unique secret "
                    "(≥32 chars) via the platform secret store, never in source control."
                )

            # Cookies over HTTPS in production
            if bool(getattr(self, "AUTH_COOKIE_ENABLED", False)):
                object.__setattr__(self, "AUTH_COOKIE_SECURE", True)

            force_https = getattr(self, "FORCE_HTTPS", None)
            if force_https is None or force_https:
                log.info(
                    "HTTPS enforcement enabled (FORCE_HTTPS=%s TRUST_PROXY_HEADERS=%s)",
                    force_https if force_https is not None else "auto",
                    bool(getattr(self, "TRUST_PROXY_HEADERS", True)),
                )

            if not (self.NVIDIA_API_KEY or "").strip() and self.nim_endpoint_count() < 1:
                raise RuntimeError(
                    "NVIDIA_API_KEY (or NIM_API_KEYS / NIM_ENDPOINT_*_API_KEY) must be set "
                    "when APP_ENV=production — LLM map/compile will fail without it."
                )

            backend = (self.OBJECT_STORAGE_BACKEND or "local").strip().lower()
            if backend == "r2":
                missing_r2 = [
                    name
                    for name, val in (
                        ("R2_ACCOUNT_ID", self.R2_ACCOUNT_ID),
                        ("R2_ACCESS_KEY_ID", self.R2_ACCESS_KEY_ID),
                        ("R2_SECRET_ACCESS_KEY", self.R2_SECRET_ACCESS_KEY),
                        ("R2_BUCKET", self.R2_BUCKET),
                    )
                    if not (val or "").strip()
                ]
                if missing_r2:
                    raise RuntimeError(
                        "OBJECT_STORAGE_BACKEND=r2 requires "
                        + ", ".join(missing_r2)
                        + " when APP_ENV=production"
                    )
            elif backend == "local":
                log.warning(
                    "OBJECT_STORAGE_BACKEND=local in production — uploads live on the "
                    "container filesystem and are lost on redeploy. Prefer r2."
                )
            elif backend == "s3":
                if not (self.AWS_ACCESS_KEY_ID and self.AWS_SECRET_ACCESS_KEY and self.AWS_S3_BUCKET):
                    raise RuntimeError(
                        "OBJECT_STORAGE_BACKEND=s3 requires AWS_ACCESS_KEY_ID, "
                        "AWS_SECRET_ACCESS_KEY, and AWS_S3_BUCKET in production"
                    )

            if require_cors:
                origins = self.cors_allow_origins()
                if origins != ["*"]:
                    only_loopback = all(
                        ("localhost" in o or "127.0.0.1" in o) for o in origins
                    )
                    if only_loopback:
                        raise RuntimeError(
                            "CORS_ORIGINS in production must include the public frontend "
                            "origin (e.g. https://*.vercel.app) or '*'; localhost-only "
                            "origins will block Vercel browsers."
                        )

            if bool(getattr(self, "AUTH_COOKIE_ENABLED", False)) and not bool(
                getattr(self, "AUTH_COOKIE_SECURE", False)
            ):
                log.warning(
                    "AUTH_COOKIE_ENABLED without AUTH_COOKIE_SECURE=true — "
                    "set AUTH_COOKIE_SECURE=true behind HTTPS"
                )

            persist = (self.CHROMA_PERSIST_DIRECTORY or self.VECTOR_DB_PATH or "").strip()
            log.info("Chroma embedded persist directory=%s", persist or "(default)")
            if persist and not (
                persist.startswith("/data") or persist.startswith("/var")
            ):
                log.warning(
                    "Chroma/aux path %s is not under /data — on Render free tier this "
                    "directory is ephemeral and embeddings are lost on restart",
                    persist,
                )


settings = Settings()
# Actual resolved values for this process (env / .env / class defaults).
log_resolved_llm_model_config(settings, phase="settings_constructed")
