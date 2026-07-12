from fastapi import FastAPI, UploadFile, HTTPException, Request, Depends, Response
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging
import uuid
import os
import shutil
from typing import Dict, Any, List, Optional

from src.api.schemas import (
    SummaryResponse, CarbonData, RagQueryRequest,
    RagQueryResponse, JobStatus, SummarizeJobResponse,
    UserRegister, UserLogin, Token, UserResponse,
    ChatRequest, ProcessingInsights,
    RefreshRequest, LogoutRequest,
)
from src.db import jobs as job_store
from src.core.config import settings
from src.core import job_status as job_status_mod
from src.core.intelligent_router import normalize_routing_preference
from src.agents import models
from src.memory import storage
from src.api import auth
from src.api.health import router as health_router
from src.api.deps import get_current_user, get_optional_user, assert_document_owner, assert_conversation_owner
from src.api.request_logging import RequestLoggingMiddleware

# --- Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# Scratch dir for triage/orchestrator (download-from-object-store → local path).
# Durable bytes live in object storage (R2/S3/local), not here.
UPLOAD_DIR = "temp_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _safe_filename(name: Optional[str]) -> str:
    base = os.path.basename(name or "upload.bin")
    cleaned = "".join(c if c.isalnum() or c in "._- " else "_" for c in base).strip()
    return (cleaned or "upload.bin")[:180]


# --- Startup/Shutdown Events ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    This function runs on application startup.
    1. Validates runtime config (env, JWT, CORS).
    2. Loads the NVIDIA NIM client.
    3. Initializes relational DB; probes Chroma without long blocking waits.
    4. Optionally starts an in-process embedded worker thread (free-tier).

    Critical for Render: uvicorn does not bind PORT until this lifespan
    completes. Embedded Chroma init is local disk only (no network waits).

    RUN_EMBEDDED_WORKER runs the durable worker in a daemon thread inside
    this process (shared NIM/Chroma memory) — NOT a second Python process,
    which OOMs free-tier instances and causes 502s during jobs.
    """
    import threading

    from src.worker.loop import request_shutdown, run_worker_forever

    log.info("API Startup: validating configuration...")
    settings.validate_for_runtime()

    # Clear scratch downloads only (object store is durable)
    if os.path.exists(UPLOAD_DIR):
        try:
            shutil.rmtree(UPLOAD_DIR)
            os.makedirs(UPLOAD_DIR, exist_ok=True)
            log.info("Cleared temp_uploads scratch directory.")
        except Exception as e:
            log.warning(f"Could not clear temp_uploads: {e}")

    log.info("Startup checks complete.")

    # 2. Load NVIDIA NIM client (no local HF model downloads)
    models.load_all_models()

    # 3. Relational DB + embedded Chroma (local disk — no remote wait)
    storage.init_database(block_on_chroma=False)

    worker_thread: Optional[threading.Thread] = None
    if getattr(settings, "RUN_EMBEDDED_WORKER", False):
        wid = (settings.WORKER_ID or "").strip() or "embedded-api-1"
        log.info("Starting in-process embedded worker thread (WORKER_ID=%s)", wid)
        worker_thread = threading.Thread(
            target=run_worker_forever,
            kwargs={"worker_id": wid, "embedded": True},
            name="embedded-durable-worker",
            daemon=True,
        )
        worker_thread.start()

    yield

    log.info("API Shutdown: draining requests (uvicorn graceful timeout)...")
    if worker_thread is not None:
        request_shutdown("api-lifespan")
        grace = float(getattr(settings, "WORKER_SHUTDOWN_GRACE_SEC", 120) or 120)
        worker_thread.join(timeout=min(grace, 60.0))
        if worker_thread.is_alive():
            log.warning("Embedded worker thread still alive after join timeout")


# --- Create FastAPI App ---
app = FastAPI(
    title=settings.APP_NAME,
    description="Green Agentic Document Intelligence API",
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

# --- CORS Middleware (env-driven; see CORS_ORIGINS / CORS_ALLOW_ALL / APP_ENV) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins(),
    allow_credentials=settings.cors_allow_credentials(),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Access logs (Phase 5 operational validation)
app.add_middleware(RequestLoggingMiddleware)

# Health / readiness (Phase 0)
app.include_router(health_router)

# --- Helper Function ---
async def ingest_upload_to_object_storage(
    file: UploadFile,
    *,
    user_id: int,
) -> Dict[str, Any]:
    """
    Persist upload bytes in object storage; Postgres gets metadata only.
    Returns job_id, document_id, storage_key, original_filename, content_type, byte_size.
    """
    from src.storage import get_object_storage

    job_id = str(uuid.uuid4())
    document_id = job_id
    original = _safe_filename(file.filename)
    content_type = file.content_type or "application/octet-stream"
    storage_key = f"documents/{user_id}/{document_id}/{original}"

    try:
        contents = await file.read()
        if not contents:
            raise HTTPException(status_code=400, detail="Empty upload.")
        store = get_object_storage()
        stored = store.put_bytes(
            storage_key,
            contents,
            content_type=content_type,
            original_filename=original,
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error storing upload: {e}")
        raise HTTPException(status_code=500, detail="Error saving uploaded file.") from e

    storage.save_document_file_metadata(
        document_id,
        user_id=user_id,
        storage_key=stored.storage_key,
        file_url=stored.file_url,
        original_filename=original,
        content_type=content_type,
        byte_size=stored.byte_size,
    )

    return {
        "job_id": job_id,
        "document_id": document_id,
        "storage_key": stored.storage_key,
        "original_filename": original,
        "content_type": content_type,
        "byte_size": stored.byte_size,
        "file_url": stored.file_url,
    }


# --- API Endpoints ---

@app.get("/")
def read_root():
    """Root liveness (kept for backwards compatibility). Prefer GET /api/health."""
    return {
        "status": "ok",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "message": "Green Agentic API is running.",
        "health": "/api/health",
        "ready": "/api/ready",
        "worker_health": "/api/worker/health",
    }


@app.get("/api/worker/health")
def worker_health(response: Response):
    """
    Worker heartbeat status (Phase 3).
    Returns 200 if at least one worker heartbeat is fresh; 503 otherwise.
    """
    from fastapi import status as http_status

    workers = job_store.list_worker_heartbeats()
    alive = [w for w in workers if w.get("alive")]
    body = {
        "status": "ok" if alive else "no_live_workers",
        "alive_count": len(alive),
        "workers": workers,
        "stale_after_sec": settings.WORKER_HEARTBEAT_STALE_SEC,
    }
    if not alive:
        response.status_code = http_status.HTTP_503_SERVICE_UNAVAILABLE
    return body


@app.post("/summarize", response_model=SummarizeJobResponse)
async def summarize_document(
    file: UploadFile,
    mode: str = "automatic",
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Enqueue a summarization job (Phase 3).

    API only: validate → upload to object storage → create pending job → return job_id.
    Long-running AI work runs in the durable worker process (``python -m src.worker``).
    """
    preference = normalize_routing_preference(mode)
    user_id = int(current_user["id"])
    log.info(f"Received file: {file.filename} (Type: {file.content_type}) (preference: {preference})")

    meta = await ingest_upload_to_object_storage(file, user_id=user_id)
    job_store.enqueue_job(
        meta["job_id"],
        user_id=user_id,
        filename=meta["original_filename"],
        job_mode=preference,
    )

    return SummarizeJobResponse(
        job_id=meta["job_id"],
        document_id=meta["document_id"],
        message="Job queued. Poll /job-status/{job_id}; processed by durable worker.",
    )


@app.get("/job-status/{job_id}", response_model=JobStatus)
def get_job_status(
    job_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Endpoint for the frontend to poll for job status.
    """
    assert_document_owner(int(current_user["id"]), job_id)
    status_dict = job_store.get_job(job_id)
    if not status_dict:
        raise HTTPException(status_code=404, detail="Job not found.")
    
    try:
        return JobStatus(
            job_id=job_id,
            status=str(status_dict.get("status") or "pending"),
            progress=float(status_dict.get("progress") or 0.0),
            message=str(status_dict.get("message") or ""),
            understanding=status_dict.get("understanding"),
        )
    except Exception as e:
        log.error(f"Error validating job status for {job_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error validating status: {status_dict}")


@app.get("/job-result/{job_id}", response_model=SummaryResponse)
def get_job_result(
    job_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Endpoint for the frontend to get the *final* result
    once the job status is canonical ``complete`` and a result payload exists.

    Convention: ``document_id`` in the result equals ``job_id`` and is the key
    to use for ``POST /rag-query``.
    """
    assert_document_owner(int(current_user["id"]), job_id)
    status = job_store.get_job(job_id)
    if not status:
        raise HTTPException(status_code=404, detail="Job not found.")
    if not job_status_mod.is_job_ready_for_result(status):
        current = job_status_mod.normalize_job_status(status.get("status"))
        raise HTTPException(
            status_code=400,
            detail=f"Job is not yet complete (status={current}).",
        )

    return SummaryResponse(**status["result"])


@app.post("/rag-query", response_model=RagQueryResponse)
def query_document(
    request: RagQueryRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    RAG endpoint: retrieve → assemble → Response Agent → optional AnswerEnvelope.
    """
    assert_document_owner(int(current_user["id"]), request.document_id)
    if request.conversation_id:
        assert_conversation_owner(
            int(current_user["id"]), request.conversation_id, request.document_id
        )
    return _run_rag_query(
        document_id=request.document_id,
        query=request.query,
        conversation_id=request.conversation_id,
        user_id=int(current_user["id"]),
    )


@app.post("/chat", response_model=RagQueryResponse)
def chat_document(
    request: ChatRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Phase 2.H — multi-turn chat; persists entity resolutions in conversation memory (TTL).
    """
    from src.memory.service import MemoryService

    uid = int(current_user["id"])
    assert_document_owner(uid, request.document_id)
    if request.conversation_id:
        assert_conversation_owner(uid, request.conversation_id, request.document_id)

    mem = MemoryService()
    state = mem.start_conversation(
        request.document_id, request.conversation_id, user_id=uid
    )
    return _run_rag_query(
        document_id=request.document_id,
        query=request.query,
        conversation_id=state.conversation_id,
        persist_conversation=True,
        user_id=uid,
    )


def _run_rag_query(
    *,
    document_id: str,
    query: str,
    conversation_id: Optional[str] = None,
    persist_conversation: bool = False,
    user_id: Optional[int] = None,
) -> RagQueryResponse:
    log.info(f"RAG Query: Doc ID {document_id}, Query: {query}")

    prior_entities: List[str] = []
    mem = None
    if conversation_id:
        from src.memory.service import MemoryService

        mem = MemoryService()
        prior_entities = mem.prior_entity_resolutions(conversation_id)

    try:
        routing = storage.get_routing_decision(document_id)
        assemble_tier = "heavy"
        if routing and settings.USE_CONTEXT_ASSEMBLER:
            assemble_tier = (
                routing.get("compile_tier")
                or routing.get("tier")
                or "heavy"
            )

        pack = None
        context_chunks = None
        retrieval_debug: Dict[str, Any] = {}

        if settings.USE_CONTEXT_ASSEMBLER or settings.USE_RESPONSE_AGENT:
            from src.retrieval.service import RetrievalService
            from src.context.assembler import ContextAssembler

            retrieval = RetrievalService().search(
                query=query,
                document_id=document_id,
            )
            retrieval_debug = dict(retrieval.debug or {})
            pack = ContextAssembler().pack(
                retrieval.passages,
                tier=assemble_tier,
                query=query,
            )
            if not pack.passages and not pack.context_text:
                raise HTTPException(
                    status_code=404,
                    detail="No relevant context found for this query.",
                )
            log.info(
                "ContextPack: tokens=%s/%s packed=%s tier=%s",
                pack.tokens_used,
                pack.tokens_budget,
                pack.stats.get("packed"),
                assemble_tier,
            )
        else:
            context_chunks = storage.search_similar_chunks(
                query=query,
                document_id=document_id,
            )
            if not context_chunks:
                raise HTTPException(
                    status_code=404,
                    detail="No relevant context found for this query.",
                )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error during vector search: {e}")
        raise HTTPException(status_code=500, detail="Error searching document.")

    try:
        skill = None
        model_used = None
        answer = ""
        sources: List[str] = []
        tier = "heavy"
        response_debug: Dict[str, Any] = {}

        if settings.USE_RESPONSE_AGENT:
            from src.agents.response_agent import ResponseAgent

            result = ResponseAgent().answer(
                query,
                pack=pack,
                context_chunks=context_chunks,
                document_id=document_id,
                routing_decision=routing,
            )
            log.info(
                "ResponseAgent: skill=%s model_used=%s tier=%s",
                result.skill,
                result.model_used,
                result.tier,
            )
            answer = result.answer
            sources = result.sources
            skill = result.skill
            model_used = result.model_used
            tier = result.tier
            response_debug = dict(result.debug or {})
            pack = result.pack or pack
        elif pack is not None:
            answer, _ = models.run_large_model_rag(
                query=query,
                context_str=pack.context_text,
            )
            sources = pack.source_texts
        else:
            answer, _sources = models.run_large_model_rag(
                query=query,
                context_chunks=context_chunks,
            )
            sources = [chunk.content for chunk in context_chunks]

        resp_kwargs: Dict[str, Any] = {
            "document_id": document_id,
            "query": query,
            "answer": answer,
            "sources": sources,
            "skill": skill,
            "model_used": model_used,
            "conversation_id": conversation_id,
        }

        entities_used: List[str] = []
        if settings.EXPLAINABILITY_ENABLED:
            from src.explainability.builder import ExplainabilityBuilder

            envelope = ExplainabilityBuilder().build(
                answer=answer,
                query=query,
                document_id=document_id,
                pack=pack,
                skill=skill,
                model_used=model_used,
                tier=tier,
                routing_decision=routing,
                retrieval_debug=retrieval_debug,
                prior_entities=prior_entities,
                response_debug=response_debug,
            )
            entities_used = list(envelope.entities_used)
            resp_kwargs.update(
                {
                    "confidence": envelope.confidence,
                    "knowledge_sources": envelope.knowledge_sources,
                    "retrieved_chunks": [c.to_dict() for c in envelope.retrieved_chunks],
                    "entities_used": envelope.entities_used,
                    "reasoning_path": envelope.reasoning_path,
                    "missing_context": envelope.missing_context,
                    "model": envelope.model.to_dict() if envelope.model else None,
                    "routing_ref": envelope.routing_ref,
                }
            )

        if persist_conversation and conversation_id and mem is not None:
            mem.append_turn(
                conversation_id, "user", query,
                entities=list(prior_entities), user_id=user_id,
            )
            mem.append_turn(
                conversation_id,
                "assistant",
                answer,
                entities=entities_used,
                meta={"skill": skill, "model_used": model_used},
                user_id=user_id,
            )

        return RagQueryResponse(**resp_kwargs)
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error during RAG answer synthesis: {e}")
        raise HTTPException(status_code=500, detail="Error generating answer.")

from src.api.schemas import DocumentResponse, KnowledgeResponse, GraphResponse

@app.get("/documents", response_model=List[DocumentResponse])
def get_documents(current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    List processed documents owned by the current user.
    """
    try:
        docs = storage.list_documents(user_id=int(current_user["id"]))
        return [DocumentResponse(**doc) for doc in docs]
    except Exception as e:
        log.error(f"Error fetching documents: {e}")
        raise HTTPException(status_code=500, detail="Error fetching documents.")


@app.get("/documents/{document_id}/routing")
def get_document_routing(
    document_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Return persisted RoutingDecision for a document (Smart Routing explainability).
    """
    assert_document_owner(int(current_user["id"]), document_id)
    data = storage.get_routing_decision(document_id)
    if not data:
        raise HTTPException(
            status_code=404,
            detail="Routing decision not found for this document.",
        )
    return data


@app.get("/documents/{document_id}/knowledge", response_model=KnowledgeResponse)
def get_document_knowledge(
    document_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Phase 2.F — read structured KnowledgeDocument for a document.
    Returns 404 if understanding has not produced knowledge yet.
    """
    assert_document_owner(int(current_user["id"]), document_id)
    data = storage.get_knowledge(document_id)
    if not data:
        # Reflect job status if still pending
        st = job_store.get_job(document_id) or {}
        understanding = st.get("understanding")
        if understanding == "pending":
            raise HTTPException(
                status_code=202,
                detail="Understanding still in progress. Poll again shortly.",
            )
        if understanding == "skipped" or not settings.ENABLE_UNDERSTANDING:
            raise HTTPException(
                status_code=404,
                detail="Understanding disabled or skipped for this document.",
            )
        raise HTTPException(status_code=404, detail="Knowledge not found for this document.")
    return KnowledgeResponse(
        document_id=data.get("document_id") or document_id,
        status=data.get("status") or "done",
        entities=data.get("entities") or [],
        concepts=data.get("concepts") or [],
        events=data.get("events") or [],
        topics=data.get("topics") or [],
        citations=data.get("citations") or [],
        relations=data.get("relations") or [],
        meta=data.get("meta"),
    )


@app.get("/documents/{document_id}/graph", response_model=GraphResponse)
def get_document_graph(
    document_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Phase 2.G — export document knowledge graph (nodes + edges).
    Falls back to building from knowledge_json if graph tables are empty.
    """
    assert_document_owner(int(current_user["id"]), document_id)
    try:
        from src.knowledge.graph_store import GraphStore, sync_graph_from_knowledge

        store = GraphStore()
        graph = store.get_graph(document_id)
        if not graph.nodes and not graph.edges:
            # Lazy sync from knowledge if understanding already ran
            synced = sync_graph_from_knowledge(document_id)
            if synced:
                graph = synced
        if not graph.nodes and not graph.edges:
            raise HTTPException(
                status_code=404,
                detail="Graph not found for this document. Run understanding first.",
            )
        return GraphResponse(
            document_id=document_id,
            nodes=[n.to_dict() for n in graph.nodes],
            edges=[e.to_dict() for e in graph.edges],
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error fetching graph for {document_id}: {e}")
        raise HTTPException(status_code=500, detail="Error fetching document graph.")

@app.get("/dashboard-stats")
def get_dashboard_stats(current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Get aggregated statistics for the dashboard (current user only).
    """
    try:
        return storage.get_dashboard_stats(user_id=int(current_user["id"]))
    except Exception as e:
        log.error(f"Error fetching dashboard stats: {e}")
        raise HTTPException(status_code=500, detail="Error fetching dashboard stats.")

# -----------------------------------------------------------
# Authentication Endpoints
# -----------------------------------------------------------

def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    if not getattr(settings, "AUTH_COOKIE_ENABLED", False):
        return
    kwargs = auth.cookie_kwargs()
    response.set_cookie(value=refresh_token, **kwargs)


def _clear_refresh_cookie(response: Response) -> None:
    if not getattr(settings, "AUTH_COOKIE_ENABLED", False):
        return
    kwargs = auth.cookie_kwargs()
    response.delete_cookie(
        key=kwargs["key"],
        path=kwargs.get("path", "/auth"),
        secure=kwargs.get("secure", False),
        httponly=True,
        samesite=kwargs.get("samesite", "lax"),
    )


def _refresh_from_request(request: Request, body: Optional[RefreshRequest]) -> Optional[str]:
    if body and body.refresh_token:
        return body.refresh_token
    return request.cookies.get(auth.REFRESH_COOKIE_NAME)


@app.post("/auth/register", response_model=UserResponse)
def register_user(user_data: UserRegister):
    """
    Register a new user account.
    """
    if "@" not in user_data.email or "." not in user_data.email:
        raise HTTPException(status_code=400, detail="Invalid email format")
    
    if len(user_data.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters long")
    
    hashed_password = auth.get_password_hash(user_data.password)
    
    user = storage.create_user(
        email=user_data.email,
        hashed_password=hashed_password,
        full_name=user_data.full_name
    )
    
    if user is None:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    log.info(f"New user registered: {user_data.email}")
    return UserResponse(**user)


@app.post("/auth/login", response_model=Token)
def login_user(user_data: UserLogin, request: Request, response: Response):
    """
    Authenticate user and return access + refresh tokens.
    """
    user = storage.get_user_by_email(user_data.email)
    
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    if not auth.verify_password(user_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is inactive")
    
    pair = auth.issue_token_pair(
        int(user.id),
        user_agent=request.headers.get("user-agent"),
    )
    _set_refresh_cookie(response, pair["refresh_token"])
    log.info(f"User logged in: {user_data.email}")
    return Token(**pair)


@app.post("/auth/refresh", response_model=Token)
def refresh_session(
    request: Request,
    response: Response,
    body: Optional[RefreshRequest] = None,
):
    """
    Rotate refresh token and issue a new access token.
    Accepts refresh_token in JSON body or httpOnly cookie.
    """
    raw = _refresh_from_request(request, body)
    if not raw:
        raise HTTPException(status_code=401, detail="Refresh token required")

    pair = auth.rotate_token_pair(raw, user_agent=request.headers.get("user-agent"))
    if not pair:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="Invalid or revoked refresh token")

    # Ensure user still exists / active
    user = storage.get_user_by_id(int(pair["user_id"]))
    if user is None or not user.get("is_active", True):
        auth.logout_refresh(pair["refresh_token"], revoke_all=True, user_id=int(pair["user_id"]))
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="User not found or inactive")

    _set_refresh_cookie(response, pair["refresh_token"])
    return Token(
        access_token=pair["access_token"],
        refresh_token=pair["refresh_token"],
        token_type=pair["token_type"],
        expires_in=pair["expires_in"],
    )


@app.post("/auth/logout")
def logout_user(
    request: Request,
    response: Response,
    body: Optional[LogoutRequest] = None,
    current_user: Optional[Dict[str, Any]] = Depends(get_optional_user),
):
    """
    Revoke refresh token (or all sessions for the user when authenticated + revoke_all).
    Works even if the access token is expired (refresh cookie/body still accepted).
    """
    raw = None
    revoke_all = False
    if body:
        raw = body.refresh_token
        revoke_all = bool(body.revoke_all)
    if not raw:
        raw = request.cookies.get(auth.REFRESH_COOKIE_NAME)

    uid = int(current_user["id"]) if current_user else None
    if revoke_all and uid is not None:
        auth.logout_refresh(None, revoke_all=True, user_id=uid)
    else:
        auth.logout_refresh(raw)
    _clear_refresh_cookie(response)
    return {"status": "ok"}


@app.get("/auth/me", response_model=UserResponse)
def get_current_user_info(current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Get current authenticated user's information.
    """
    return UserResponse(**current_user)
