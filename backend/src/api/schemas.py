from pydantic import BaseModel, ConfigDict
from typing import List, Optional

# This defines the structure of the Carbon Report in the final summary
class CarbonData(BaseModel):
    model_config = ConfigDict(extra="allow")

    carbon_saved_grams: float
    message: str
    total_chunks: int
    chunks_escalated: int
    local_grid_gco2_kwh: float
    remote_grid_gco2_kwh: Optional[float] = None
    compute_location: str
    # Legacy numeric fields (kept for compatibility)
    baseline_cost_gco2e: float = 0.0
    actual_cost_gco2e: float = 0.0
    efficiency_percent: float = 0.0
    # Workflow energy → Electricity Maps path
    baseline_energy_kwh: float = 0.0
    actual_energy_kwh: float = 0.0
    grid_zone: Optional[str] = None
    grid_datetime: Optional[str] = None
    grid_source: Optional[str] = None
    grid_updated_at: Optional[str] = None
    breakdown: Optional[dict] = None
    methodology: Optional[str] = None
    # Explicit estimated terminology (Boundary A operational)
    estimated_baseline_pipeline_emissions_g: float = 0.0
    estimated_optimized_pipeline_emissions_g: float = 0.0
    estimated_carbon_saved_g: float = 0.0
    estimated_reduction_percent: float = 0.0
    reporting_boundary: Optional[str] = None
    reporting_boundary_label: Optional[str] = None
    routing_impact: Optional[dict] = None
    uncertainty: Optional[dict] = None
    assumptions_panel: Optional[str] = None
    pue: Optional[float] = None
    # Flattened token rows (also nested under breakdown)
    input_tokens: Optional[int] = None
    retrieved_context_tokens: Optional[int] = None
    generated_tokens: Optional[int] = None
    effective_tokens: Optional[int] = None
    # Pre-built Job Report Card payload (tokens/energy/stages/routing)
    report_card: Optional[dict] = None


class FrontierComparisonModel(BaseModel):
    model: str
    relative_factor: float = 1.0
    estimated_gco2e: float
    saved_gco2e: float
    reduction_percent: float


class OurSystemCarbon(BaseModel):
    name: str
    tagline: Optional[str] = None
    carbon: float


class CarbonSummaryCards(BaseModel):
    actual_emissions_gco2e: float
    carbon_saved_gco2e: float
    reduction_percent: float
    heavy_model_baseline_gco2e: float
    # Preferred display labels (optional; UI falls back to legacy keys)
    estimated_optimized_pipeline_emissions_g: Optional[float] = None
    estimated_baseline_pipeline_emissions_g: Optional[float] = None
    reporting_boundary_label: Optional[str] = "Operational Emissions (Boundary A)"


class ChartBar(BaseModel):
    model: str
    estimated_gco2e: float
    is_ours: bool = False


class CarbonComparisonPayload(BaseModel):
    """Visualization layer derived from workflow carbon accounting."""
    comparison_models: List[FrontierComparisonModel] = []
    our_system: OurSystemCarbon
    summary_cards: CarbonSummaryCards
    badges: List[str] = []
    chart_bars: List[ChartBar] = []
    methodology: str = ""
    breakdown: Optional[dict] = None

# This is the response model when a job is FIRST submitted
class SummarizeJobResponse(BaseModel):
    job_id: str
    document_id: str
    message: str

# This is the response model for the /job-status endpoint
class JobStatus(BaseModel):
    job_id: str
    status: str
    progress: float
    message: str
    # Phase 2.F — async understanding: pending|done|failed|skipped
    understanding: Optional[str] = None
    # Streaming partials (populated as pipeline advances; never required)
    partial: Optional[dict] = None
    chunks_done: Optional[int] = None
    chunks_total: Optional[int] = None
    stage: Optional[str] = None
    filename: Optional[str] = None
    job_mode: Optional[str] = None
    claimed_by: Optional[str] = None
    attempt_count: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class JobListItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    job_id: str
    status: str
    progress: float = 0.0
    message: str = ""
    filename: Optional[str] = None
    job_mode: Optional[str] = None
    claimed_by: Optional[str] = None
    attempt_count: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class JobListResponse(BaseModel):
    jobs: List[JobListItem]
    count: int


class QueueSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    alive_workers: int = 0
    worker_busy: bool = False
    queued_count: int = 0
    processing_count: int = 0
    workers: List[dict] = []
    active_jobs: List[JobListItem] = []


class CancelJobResponse(BaseModel):
    job_id: str
    status: str
    message: str
    freed_worker: bool = False

# This is the response model for the FINAL /job-result endpoint
class EscalationInsight(BaseModel):
    required: bool = False
    chunks_escalated: int = 0
    details: List[dict] = []


class ProcessingInsights(BaseModel):
    """Smart Routing explainability for summarize jobs."""
    model_config = ConfigDict(extra="allow")

    crs: Optional[float] = None
    document_type: Optional[str] = None
    selected_model: Optional[str] = None
    tier: Optional[str] = None
    compile_tier: Optional[str] = None
    retrieval_strategy: Optional[str] = "Hybrid Dense + Sparse + Reranking"
    escalation: Optional[EscalationInsight] = None
    carbon_optimization_applied: bool = True
    latency_ms: Optional[float] = None
    confidence: Optional[float] = None
    reason_summary: Optional[str] = None
    routing_preference: Optional[str] = None
    domain_risk: Optional[dict] = None
    policy_version: Optional[str] = None
    min_tier: Optional[str] = None
    # Adaptive hierarchical pipeline
    routing_distribution: Optional[dict] = None
    validation_pass_rate: Optional[float] = None
    average_confidence: Optional[float] = None
    average_semantic_similarity: Optional[float] = None
    carbon_by_agent: Optional[dict] = None
    latency_by_agent: Optional[dict] = None
    hierarchy: Optional[dict] = None
    compile_meta: Optional[dict] = None
    carbon_budget: Optional[dict] = None
    processing_timeline: Optional[List[dict]] = None
    chunk_routing_sample: Optional[List[dict]] = None


class SummaryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    document_id: str
    filename: str
    final_summary: str
    carbon_data: CarbonData
    job_id: str
    processing_insights: Optional[ProcessingInsights] = None
    # Diagnostic stage + per-chunk timings (optional)
    ingestion_latency: Optional[dict] = None
    hierarchy: Optional[dict] = None
    routing_distribution: Optional[dict] = None
    chunk_routing: Optional[List[dict]] = None
    compile_meta: Optional[dict] = None
    carbon_budget: Optional[dict] = None
    # Visualization layer — does not alter scheduler carbon accounting
    comparison_models: Optional[List[FrontierComparisonModel]] = None
    our_system: Optional[OurSystemCarbon] = None
    summary_cards: Optional[CarbonSummaryCards] = None
    badges: Optional[List[str]] = None
    chart_bars: Optional[List[ChartBar]] = None
    methodology: Optional[str] = None
    carbon_comparison: Optional[CarbonComparisonPayload] = None

# This is the request model for the /rag-query endpoint
class RagQueryRequest(BaseModel):
    document_id: str
    query: str
    conversation_id: Optional[str] = None  # Phase 2.H optional multi-turn


# This is the response model for the /rag-query endpoint
class RagQueryResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    document_id: str
    query: str
    answer: str
    sources: List[str]  # The text chunks used as context
    # Phase 2.D — optional, backward compatible
    skill: Optional[str] = None
    model_used: Optional[str] = None
    # Phase 2.H — AnswerEnvelope fields (optional; omitted when explainability off)
    confidence: Optional[float] = None
    knowledge_sources: Optional[List[str]] = None
    retrieved_chunks: Optional[List[dict]] = None
    entities_used: Optional[List[str]] = None
    reasoning_path: Optional[List[str]] = None
    missing_context: Optional[List[str]] = None
    model: Optional[dict] = None
    routing_ref: Optional[str] = None
    conversation_id: Optional[str] = None
    # Query-path stage timing (ms). Present when instrumentation is enabled.
    # Shape: {"stages_ms": {...}, "meta": {...}}
    latency: Optional[dict] = None


class ChatRequest(BaseModel):
    """Phase 2.H — multi-turn chat over a document."""
    document_id: str
    query: str
    conversation_id: Optional[str] = None

class DocumentResponse(BaseModel):
    document_id: str
    summary: str
    saved_at: Optional[str] = None
    carbon_saved: Optional[float] = 0.0
    efficiency: Optional[float] = 0.0


class KnowledgeResponse(BaseModel):
    """Phase 2.F — structured knowledge for a document."""
    document_id: str
    status: str
    entities: List[dict] = []
    concepts: List[dict] = []
    events: List[dict] = []
    topics: List[dict] = []
    citations: List[dict] = []
    relations: List[dict] = []
    meta: Optional[dict] = None


class GraphResponse(BaseModel):
    """Phase 2.G — document knowledge graph export."""
    document_id: str
    nodes: List[dict] = []
    edges: List[dict] = []

# -----------------------------------------------------------
# Authentication Schemas
# -----------------------------------------------------------

class UserRegister(BaseModel):
    """Schema for user registration"""
    email: str
    password: str
    full_name: str

class UserLogin(BaseModel):
    """Schema for user login"""
    email: str
    password: str

class Token(BaseModel):
    """JWT access token response; refresh_token added in Phase 1 (optional for old clients)."""
    access_token: str
    token_type: str = "bearer"
    refresh_token: Optional[str] = None
    expires_in: Optional[int] = None


class RefreshRequest(BaseModel):
    """Body refresh; cookie also accepted when AUTH_COOKIE_ENABLED."""
    refresh_token: Optional[str] = None


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None
    revoke_all: bool = False


class UserResponse(BaseModel):
    """Schema for user information (without password)"""
    id: int
    email: str
    full_name: str
    is_active: bool
    created_at: Optional[str] = None
