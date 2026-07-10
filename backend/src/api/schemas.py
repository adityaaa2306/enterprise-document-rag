from pydantic import BaseModel, ConfigDict
from typing import List, Optional

# This defines the structure of the Carbon Report in the final summary
class CarbonData(BaseModel):
    carbon_saved_grams: float
    message: str
    total_chunks: int
    chunks_escalated: int
    local_grid_gco2_kwh: float
    remote_grid_gco2_kwh: Optional[float] = None
    compute_location: str
    baseline_cost_gco2e: float = 0.0
    actual_cost_gco2e: float = 0.0
    efficiency_percent: float = 0.0

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

# This is the response model for the FINAL /job-result endpoint
class EscalationInsight(BaseModel):
    required: bool = False
    chunks_escalated: int = 0
    details: List[dict] = []


class ProcessingInsights(BaseModel):
    """Smart Routing explainability for summarize jobs."""
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


class SummaryResponse(BaseModel):
    document_id: str
    filename: str
    final_summary: str
    carbon_data: CarbonData
    job_id: str
    processing_insights: Optional[ProcessingInsights] = None

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
