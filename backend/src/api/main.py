from fastapi import FastAPI, UploadFile, HTTPException, Request, Depends, Response, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from contextlib import asynccontextmanager
import asyncio
import json
import logging
import re
import uuid
import os
import shutil
from typing import Dict, Any, List, Optional, AsyncIterator

from src.api.schemas import (
    SummaryResponse, CarbonData, RagQueryRequest,
    RagQueryResponse, JobStatus, SummarizeJobResponse,
    UserRegister, UserLogin, Token, UserResponse,
    ChatRequest, ProcessingInsights,
    RefreshRequest, LogoutRequest,
    JobListResponse, JobListItem, QueueSnapshotResponse, CancelJobResponse,
)
from src.core.frontier_carbon_compare import build_frontier_comparison
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


def _serialize_job_ts(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _job_list_item(raw: Dict[str, Any]) -> JobListItem:
    return JobListItem(
        job_id=str(raw.get("job_id") or ""),
        status=str(raw.get("status") or "pending"),
        progress=float(raw.get("progress") or 0.0),
        message=str(raw.get("message") or ""),
        filename=raw.get("filename"),
        job_mode=raw.get("job_mode"),
        claimed_by=raw.get("claimed_by"),
        attempt_count=int(raw.get("attempt_count") or 0),
        created_at=_serialize_job_ts(raw.get("created_at")),
        updated_at=_serialize_job_ts(raw.get("updated_at")),
    )


@app.get("/jobs", response_model=JobListResponse)
def list_my_jobs(
    limit: int = Query(1, ge=1, le=200),
    active_only: bool = Query(False),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Job list for the signed-in user.

    Retention (purge older jobs) runs on enqueue only — never on this read path,
    so the Results sidebar can poll without multi-second latency.
    """
    uid = int(current_user["id"])

    rows = job_store.list_jobs_for_user(
        uid,
        limit=min(limit, 1) if not active_only else limit,
        include_terminal=not active_only,
    )
    # Hard cap: never return more than one terminal history slot
    if not active_only and len(rows) > 1:
        rows = rows[:1]
    items = [_job_list_item(r) for r in rows]
    return JobListResponse(jobs=items, count=len(items))


@app.get("/queue", response_model=QueueSnapshotResponse)
def get_queue_snapshot(
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Live worker occupancy + this user's pending/processing jobs."""
    snap = job_store.queue_snapshot_for_user(int(current_user["id"]))
    return QueueSnapshotResponse(
        alive_workers=int(snap.get("alive_workers") or 0),
        worker_busy=bool(snap.get("worker_busy")),
        queued_count=int(snap.get("queued_count") or 0),
        processing_count=int(snap.get("processing_count") or 0),
        workers=list(snap.get("workers") or []),
        active_jobs=[_job_list_item(j) for j in (snap.get("active_jobs") or [])],
    )


@app.post("/jobs/{job_id}/cancel", response_model=CancelJobResponse)
def cancel_my_job(
    job_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Cancel a pending/processing job and free the worker slot."""
    assert_document_owner(int(current_user["id"]), job_id)
    try:
        updated = job_store.cancel_job(job_id, user_id=int(current_user["id"]))
    except PermissionError:
        raise HTTPException(status_code=403, detail="Not allowed to cancel this job.")
    if not updated:
        raise HTTPException(status_code=404, detail="Job not found.")
    status = str(updated.get("status") or "")
    return CancelJobResponse(
        job_id=job_id,
        status=status,
        message=str(updated.get("message") or "Cancelled."),
        freed_worker=status == job_status_mod.STATUS_CANCELLED,
    )


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
    # Single-slot retention: wipe older jobs + their RAG data for this user
    try:
        job_store.retain_only_latest_job(user_id, keep_job_id=meta["job_id"])
    except Exception as e:
        log.warning("retain_only_latest_job after enqueue failed: %s", e)

    return SummarizeJobResponse(
        job_id=meta["job_id"],
        document_id=meta["document_id"],
        message="Job queued. Poll /job-status/{job_id}; processed by durable worker.",
    )


def _parse_chunk_progress(message: str) -> tuple:
    """Extract (done, total) from messages like 'Summarizing... (3/12)'."""
    m = re.search(r"\((\d+)\s*/\s*(\d+)\)", message or "")
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def _stage_from_progress(progress: float, message: str) -> str:
    p = float(progress or 0)
    msg = (message or "").lower()
    if p >= 98:
        return "finalize"
    if p >= 90:
        return "store"
    if p >= 82:
        return "compile"
    if "escalat" in msg:
        return "escalate"
    if p >= 65:
        return "validate"
    if p >= 35:
        return "map"
    if p >= 24:
        return "plan"
    if p >= 20:
        return "features"
    if p >= 12:
        return "triage"
    return "queued"


def _job_status_payload(job_id: str, status_dict: Dict[str, Any]) -> JobStatus:
    status = str(status_dict.get("status") or "pending")
    progress = float(status_dict.get("progress") or 0.0)
    message = str(status_dict.get("message") or "")
    done, total = _parse_chunk_progress(message)
    stage = _stage_from_progress(progress, message)
    partial = status_dict.get("partial") if isinstance(status_dict.get("partial"), dict) else None
    return JobStatus(
        job_id=job_id,
        status=status,
        progress=progress,
        message=message,
        understanding=status_dict.get("understanding"),
        partial=partial,
        chunks_done=done,
        chunks_total=total,
        stage=stage,
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

    # Heal race: result already persisted but a late heartbeat left status=processing.
    status = str(status_dict.get("status") or "pending")
    if (
        status == job_status_mod.STATUS_PROCESSING
        and isinstance(status_dict.get("result"), dict)
        and status_dict["result"].get("final_summary")
        and float(status_dict.get("progress") or 0.0) >= 100.0
    ):
        job_store.upsert_job(
            job_id,
            status=job_status_mod.STATUS_COMPLETE,
            progress=100.0,
            message="Job complete. Results are ready.",
            result=status_dict.get("result"),
            claimed_by=None,
            heartbeat_at=None,
        )
        status_dict = job_store.get_job(job_id) or status_dict
        status = str(status_dict.get("status") or status)

    try:
        return _job_status_payload(job_id, status_dict)
    except Exception as e:
        log.error(f"Error validating job status for {job_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error validating status: {status_dict}")


@app.get("/job-events/{job_id}")
async def job_events_sse(
    job_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Server-Sent Events stream of job progress (Phase 13).

    Emits ``progress`` events as status changes; closes on terminal status.
    Auth via same Bearer token as polling (EventSource polyfill / fetch stream).
    """
    assert_document_owner(int(current_user["id"]), job_id)

    async def _gen() -> AsyncIterator[str]:
        last_key = None
        terminal = {
            job_status_mod.STATUS_COMPLETE,
            job_status_mod.STATUS_ERROR,
            job_status_mod.STATUS_CANCELLED,
            "complete",
            "error",
            "cancelled",
            "failed",
        }
        # Cap stream lifetime (~45 min)
        for _ in range(2700):
            status_dict = job_store.get_job(job_id) or {}
            if not status_dict:
                yield f"event: error\ndata: {json.dumps({'error': 'not_found'})}\n\n"
                return
            payload = _job_status_payload(job_id, status_dict)
            key = (payload.status, round(payload.progress, 1), payload.message)
            if key != last_key:
                last_key = key
                data = payload.model_dump()
                yield f"event: progress\ndata: {json.dumps(data)}\n\n"
                if str(payload.status).lower() in terminal or payload.progress >= 100.0:
                    yield f"event: done\ndata: {json.dumps(data)}\n\n"
                    return
            await asyncio.sleep(0.5)

        yield f"event: timeout\ndata: {json.dumps({'error': 'stream_timeout'})}\n\n"

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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

    Attaches a visualization-only frontier carbon comparison derived from the
    already-computed ``carbon_data`` (does not alter scheduler accounting).
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

    result = dict(status["result"] or {})
    carbon = result.get("carbon_data") if isinstance(result.get("carbon_data"), dict) else {}
    carbon = dict(carbon)

    # Sanitize legacy chunk×grams baselines before building comparison bars.
    try:
        baseline = float(carbon.get("baseline_cost_gco2e") or 0.0)
        energy = float(carbon.get("baseline_energy_kwh") or 0.0)
        intensity = float(carbon.get("local_grid_gco2_kwh") or 0.0)
        bd = carbon.get("breakdown") if isinstance(carbon.get("breakdown"), dict) else {}
        if energy <= 0:
            energy = float(bd.get("baseline_energy_kwh") or 0.0)
        if intensity <= 0:
            intensity = float(bd.get("grid_carbon_intensity_gco2_kwh") or 0.0)
        if baseline > 150 and energy > 0 and intensity > 0:
            rebuilt = energy * intensity
            if 0 < rebuilt < baseline:
                carbon["baseline_cost_gco2e"] = rebuilt
                if isinstance(bd, dict):
                    bd = dict(bd)
                    bd["baseline_co2e_g"] = round(rebuilt, 4)
                    carbon["breakdown"] = bd
                actual = float(carbon.get("actual_cost_gco2e") or 0.0)
                saved = max(0.0, rebuilt - actual)
                carbon["carbon_saved_grams"] = saved
                carbon["efficiency_percent"] = (
                    round(min(100.0, (saved / rebuilt) * 100.0), 1) if rebuilt > 0 else 0.0
                )
                result["carbon_data"] = carbon
    except (TypeError, ValueError):
        pass

    comparison = build_frontier_comparison(carbon)
    result["comparison_models"] = comparison["comparison_models"]
    result["our_system"] = comparison["our_system"]
    result["summary_cards"] = comparison["summary_cards"]
    result["badges"] = comparison["badges"]
    result["chart_bars"] = comparison["chart_bars"]
    result["methodology"] = comparison["methodology"]
    result["carbon_comparison"] = comparison
    # Always serve canonical Boundary-A copy + a complete breakdown so the
    # Job Report Card cannot show legacy ChatGPT-class text or empty tokens.
    if isinstance(result.get("carbon_data"), dict):
        from src.carbon.accounting import (
            ASSUMPTIONS_PANEL_TEXT,
            METHODOLOGY_TEXT as CARBON_METHODOLOGY_TEXT,
        )

        cd = dict(result["carbon_data"])
        bd = cd.get("breakdown") if isinstance(cd.get("breakdown"), dict) else {}
        bd = dict(bd)
        if comparison.get("breakdown") and isinstance(comparison["breakdown"], dict):
            # Prefer richer stored breakdown; fill any missing keys from comparison.
            for k, v in comparison["breakdown"].items():
                bd.setdefault(k, v)
        # Promote top-level energy/grid fields into breakdown when absent
        # (older recomputes sometimes stored grams without token rows).
        _promote = {
            "baseline_energy_kwh": cd.get("baseline_energy_kwh"),
            "optimized_energy_kwh": cd.get("actual_energy_kwh"),
            "grid_carbon_intensity_gco2_kwh": cd.get("local_grid_gco2_kwh"),
            "grid_zone": cd.get("grid_zone") or cd.get("compute_location"),
            "grid_datetime": cd.get("grid_datetime"),
            "baseline_co2e_g": cd.get("baseline_cost_gco2e"),
            "actual_co2e_g": cd.get("actual_cost_gco2e"),
            "carbon_saved_g": cd.get("carbon_saved_grams"),
            "reduction_percent": cd.get("efficiency_percent"),
            "estimated_baseline_pipeline_emissions_g": cd.get(
                "estimated_baseline_pipeline_emissions_g"
            )
            or cd.get("baseline_cost_gco2e"),
            "estimated_optimized_pipeline_emissions_g": cd.get(
                "estimated_optimized_pipeline_emissions_g"
            )
            or cd.get("actual_cost_gco2e"),
        }
        for k, v in _promote.items():
            if k not in bd and v is not None:
                bd[k] = v
            elif bd.get(k) is None and v is not None:
                bd[k] = v
        bd["assumptions_panel"] = ASSUMPTIONS_PANEL_TEXT
        bd["reporting_boundary_label"] = (
            bd.get("reporting_boundary_label")
            or cd.get("reporting_boundary_label")
            or "Operational Emissions (Boundary A)"
        )
        cd["breakdown"] = bd
        cd["assumptions_panel"] = ASSUMPTIONS_PANEL_TEXT
        cd["methodology"] = CARBON_METHODOLOGY_TEXT
        cd["reporting_boundary_label"] = bd["reporting_boundary_label"]
        # Flatten every Job Report Card field onto carbon_data top-level so the
        # UI never depends on nested breakdown surviving transport/caching.
        _flat_copy = {
            "input_tokens": bd.get("input_tokens"),
            "retrieved_context_tokens": bd.get("retrieved_context_tokens"),
            "generated_tokens": bd.get("generated_tokens"),
            "effective_tokens": bd.get("effective_tokens"),
            "grid_updated_at": bd.get("grid_updated_at") or bd.get("grid_datetime"),
            "baseline_energy_kwh": bd.get("baseline_energy_kwh")
            or cd.get("baseline_energy_kwh"),
            "actual_energy_kwh": bd.get("optimized_energy_kwh")
            or cd.get("actual_energy_kwh"),
            "routing_impact": bd.get("routing_impact") or cd.get("routing_impact"),
            "uncertainty": bd.get("uncertainty") or cd.get("uncertainty"),
        }
        for k, v in _flat_copy.items():
            if v is not None:
                cd[k] = v
        # Dedicated report-card block (frontend reads this first).
        cd["report_card"] = {
            "input_tokens": cd.get("input_tokens"),
            "retrieved_context_tokens": cd.get("retrieved_context_tokens"),
            "generated_tokens": cd.get("generated_tokens"),
            "effective_tokens": cd.get("effective_tokens"),
            "baseline_energy_kwh": cd.get("baseline_energy_kwh"),
            "optimized_energy_kwh": cd.get("actual_energy_kwh"),
            "grid_carbon_intensity_gco2_kwh": cd.get("local_grid_gco2_kwh"),
            "grid_zone": cd.get("grid_zone") or cd.get("compute_location"),
            "grid_updated_at": cd.get("grid_updated_at") or cd.get("grid_datetime"),
            "estimated_baseline_pipeline_emissions_g": cd.get(
                "estimated_baseline_pipeline_emissions_g"
            )
            or cd.get("baseline_cost_gco2e"),
            "estimated_optimized_pipeline_emissions_g": cd.get(
                "estimated_optimized_pipeline_emissions_g"
            )
            or cd.get("actual_cost_gco2e"),
            "estimated_carbon_saved_g": cd.get("carbon_saved_grams"),
            "estimated_reduction_percent": cd.get("efficiency_percent"),
            "emissions_direction": cd.get("emissions_direction")
            or bd.get("emissions_direction"),
            "optimized_stages_gco2e": bd.get("optimized_stages_gco2e"),
            "baseline_stages_gco2e": bd.get("baseline_stages_gco2e"),
            "chunk_breakdown": cd.get("chunk_breakdown") or bd.get("chunk_breakdown"),
            "routing_impact": cd.get("routing_impact"),
            "uncertainty": cd.get("uncertainty"),
            "assumptions_panel": ASSUMPTIONS_PANEL_TEXT,
            "baseline_definition": bd.get("baseline_definition"),
            "optimized_definition": bd.get("optimized_definition"),
            "reporting_boundary_label": cd.get("reporting_boundary_label"),
        }
        result["carbon_data"] = cd
        # Keep frontier methodology for the comparison panel, but ensure
        # carbon_data.methodology is always Boundary-A operational copy.
        result["methodology"] = comparison["methodology"]
    return SummaryResponse(**result)


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


@app.post("/rag-query/stream")
def query_document_stream(
    request: RagQueryRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    True SSE streaming: tokens as they arrive from NIM, explainability in final event.
    Events: meta | token | done | error (JSON lines as ``data: {...}\\n\\n``).
    """
    assert_document_owner(int(current_user["id"]), request.document_id)
    if request.conversation_id:
        assert_conversation_owner(
            int(current_user["id"]), request.conversation_id, request.document_id
        )
    return StreamingResponse(
        _iter_rag_query_sse(
            document_id=request.document_id,
            query=request.query,
            conversation_id=request.conversation_id,
            user_id=int(current_user["id"]),
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
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


def _sse_line(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


def _iter_rag_query_sse(
    *,
    document_id: str,
    query: str,
    conversation_id: Optional[str] = None,
    user_id: Optional[int] = None,
):
    """Generator that yields SSE frames for /rag-query/stream."""
    import time
    import threading

    from src.monitoring.query_latency import (
        STAGE_CITATIONS,
        STAGE_CONTEXT_ASSEMBLE,
        STAGE_EXPLAINABILITY,
        log_query_latency,
        merge_latency,
    )
    from src.monitoring.query_path_guard import (
        begin_query_path,
        end_query_path,
        snapshot_violations,
    )
    from src.perf.profiler import attach_resource_snapshot, sample_resources

    t_request = time.perf_counter()
    begin_query_path(document_id=document_id, query=query)
    resources_start = sample_resources()
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

        from src.retrieval.service import RetrievalService
        from src.context.assembler import ContextAssembler

        retrieval = RetrievalService().search(
            query=query,
            document_id=document_id,
        )
        retrieval_debug = dict(retrieval.debug or {})
        retrieval_latency = dict(retrieval_debug.get("latency") or {})
        pack = ContextAssembler().pack(
            retrieval.passages,
            tier=assemble_tier,
            query=query,
        )
        assemble_ms = (pack.stats or {}).get("latency_ms") or {}
        assemble_latency = (
            {"stages_ms": dict(assemble_ms), "meta": {}} if assemble_ms else {}
        )
        if not pack.passages and not pack.context_text:
            yield _sse_line(
                {
                    "event": "error",
                    "message": "No relevant context found for this query.",
                    "status": 404,
                }
            )
            return

        pre_ms = (time.perf_counter() - t_request) * 1000.0
        yield _sse_line(
            {
                "event": "meta",
                "document_id": document_id,
                "retrieval_ms": round(pre_ms, 1),
                "context_tokens": pack.tokens_used,
                "context_budget": pack.tokens_budget,
                "packed": (pack.stats or {}).get("packed"),
            }
        )

        from src.agents.response_agent import ResponseAgent

        answer = ""
        skill = None
        model_used = None
        tier = assemble_tier
        sources: List[str] = []
        response_debug: Dict[str, Any] = {}
        llm_latency: Dict[str, Any] = {}
        client_ttft_ms: Optional[float] = None
        t_first_token_client: Optional[float] = None

        for ev in ResponseAgent().answer_stream(
            query,
            pack=pack,
            document_id=document_id,
            routing_decision=routing,
        ):
            event = ev.get("event")
            if event == "meta":
                # Already sent retrieval meta; enrich with plan
                yield _sse_line(
                    {
                        "event": "plan",
                        "skill": ev.get("skill"),
                        "response_plan": ev.get("response_plan"),
                    }
                )
            elif event == "token":
                if t_first_token_client is None:
                    t_first_token_client = time.perf_counter()
                    client_ttft_ms = (t_first_token_client - t_request) * 1000.0
                yield _sse_line({"event": "token", "text": ev.get("text") or ""})
            elif event == "error":
                yield _sse_line({"event": "error", "message": ev.get("message")})
                return
            elif event == "done":
                answer = ev.get("answer") or ""
                skill = ev.get("skill")
                model_used = ev.get("model_used")
                tier = ev.get("tier") or tier
                sources = list(ev.get("sources") or [])
                response_debug = dict(ev.get("debug") or {})
                llm_latency = dict(response_debug.get("latency") or {})
                pack = ev.get("pack") or pack

        # Explainability AFTER tokens (off critical path for perceived latency)
        explain_ms = 0.0
        cite_ms = 0.0
        entities_used: List[str] = []
        done_payload: Dict[str, Any] = {
            "event": "done",
            "document_id": document_id,
            "query": query,
            "answer": answer,
            "sources": sources,
            "skill": skill,
            "model_used": model_used,
            "conversation_id": conversation_id,
            "client_ttft_ms": round(client_ttft_ms, 3) if client_ttft_ms is not None else None,
        }

        if settings.EXPLAINABILITY_ENABLED:
            from src.explainability.builder import ExplainabilityBuilder

            t_explain = time.perf_counter()
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
            explain_ms = (time.perf_counter() - t_explain) * 1000.0
            t_cite = time.perf_counter()
            chunk_dicts = [c.to_dict() for c in envelope.retrieved_chunks]
            cite_ms = (time.perf_counter() - t_cite) * 1000.0
            entities_used = list(envelope.entities_used)
            done_payload.update(
                {
                    "confidence": envelope.confidence,
                    "knowledge_sources": envelope.knowledge_sources,
                    "retrieved_chunks": chunk_dicts,
                    "entities_used": envelope.entities_used,
                    "reasoning_path": envelope.reasoning_path,
                    "missing_context": envelope.missing_context,
                    "model": envelope.model.to_dict() if envelope.model else None,
                    "routing_ref": envelope.routing_ref,
                }
            )

        total_ms = (time.perf_counter() - t_request) * 1000.0
        latency = merge_latency(
            retrieval_latency,
            assemble_latency,
            llm_latency,
            {
                "stages_ms": {
                    STAGE_EXPLAINABILITY: round(explain_ms, 3),
                    STAGE_CITATIONS: round(cite_ms, 3),
                },
                "meta": {},
            },
            total_ms=total_ms,
        )
        if STAGE_CONTEXT_ASSEMBLE not in (latency.get("stages_ms") or {}):
            latency.setdefault("stages_ms", {})[STAGE_CONTEXT_ASSEMBLE] = 0.0

        violations = snapshot_violations()
        resources_end = sample_resources()
        latency.setdefault("meta", {})
        latency["meta"].update(
            {
                "document_id": document_id,
                "streaming": True,
                "pipeline_validation": {
                    "ingest_ops_on_query_path": violations,
                    "clean": len(violations) == 0,
                },
                "resources_start": resources_start,
                "resources_end": resources_end,
                "active_threads": threading.active_count(),
                "client_ttft_ms": (
                    round(client_ttft_ms, 3) if client_ttft_ms is not None else None
                ),
            }
        )
        llm_meta = (llm_latency.get("meta") or {}) if isinstance(llm_latency, dict) else {}
        for key in ("nim", "prompt", "llm_timing_mode"):
            if key in llm_meta and key not in latency["meta"]:
                latency["meta"][key] = llm_meta[key]
        attach_resource_snapshot(latency, label="end")
        log_query_latency(document_id=document_id, query=query, latency=latency)
        done_payload["latency"] = latency

        if conversation_id and mem is not None:
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

        yield _sse_line(done_payload)
    except Exception as e:
        log.error(f"SSE RAG stream failed: {e}")
        yield _sse_line({"event": "error", "message": str(e)})
    finally:
        end_query_path()


def _run_rag_query(
    *,
    document_id: str,
    query: str,
    conversation_id: Optional[str] = None,
    persist_conversation: bool = False,
    user_id: Optional[int] = None,
) -> RagQueryResponse:
    import time
    import threading

    from src.monitoring.query_latency import (
        STAGE_CITATIONS,
        STAGE_CONTEXT_ASSEMBLE,
        STAGE_EXPLAINABILITY,
        STAGE_LLM_TOTAL,
        log_query_latency,
        merge_latency,
    )
    from src.monitoring.query_path_guard import (
        begin_query_path,
        end_query_path,
        snapshot_violations,
    )
    from src.perf.profiler import attach_resource_snapshot, sample_resources

    log.info(f"RAG Query: Doc ID {document_id}, Query: {query}")
    t_request = time.perf_counter()
    begin_query_path(document_id=document_id, query=query)
    resources_start = sample_resources()

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
        retrieval_latency: Dict[str, Any] = {}
        assemble_latency: Dict[str, Any] = {}

        if settings.USE_CONTEXT_ASSEMBLER or settings.USE_RESPONSE_AGENT:
            from src.retrieval.service import RetrievalService
            from src.context.assembler import ContextAssembler

            retrieval = RetrievalService().search(
                query=query,
                document_id=document_id,
            )
            retrieval_debug = dict(retrieval.debug or {})
            retrieval_latency = dict(retrieval_debug.get("latency") or {})
            pack = ContextAssembler().pack(
                retrieval.passages,
                tier=assemble_tier,
                query=query,
            )
            assemble_ms = (pack.stats or {}).get("latency_ms") or {}
            if assemble_ms:
                assemble_latency = {"stages_ms": dict(assemble_ms), "meta": {}}
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
        end_query_path()
        raise
    except Exception as e:
        end_query_path()
        log.error(f"Error during vector search: {e}")
        raise HTTPException(status_code=500, detail="Error searching document.")

    try:
        skill = None
        model_used = None
        answer = ""
        sources: List[str] = []
        tier = "heavy"
        response_debug: Dict[str, Any] = {}
        llm_latency: Dict[str, Any] = {}

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
            llm_latency = dict(response_debug.get("latency") or {})
            pack = result.pack or pack
        elif pack is not None:
            t_llm = time.perf_counter()
            answer, _ = models.run_large_model_rag(
                query=query,
                context_str=pack.context_text,
            )
            llm_ms = round((time.perf_counter() - t_llm) * 1000.0, 3)
            llm_latency = {
                "stages_ms": {
                    "llm_ttft_ms": llm_ms,
                    "llm_ttlt_ms": llm_ms,
                    STAGE_LLM_TOTAL: llm_ms,
                },
                "meta": {"llm_timing_mode": "blocking_ttft_equals_ttlt"},
            }
            sources = pack.source_texts
        else:
            t_llm = time.perf_counter()
            answer, _sources = models.run_large_model_rag(
                query=query,
                context_chunks=context_chunks,
            )
            llm_ms = round((time.perf_counter() - t_llm) * 1000.0, 3)
            llm_latency = {
                "stages_ms": {
                    "llm_ttft_ms": llm_ms,
                    "llm_ttlt_ms": llm_ms,
                    STAGE_LLM_TOTAL: llm_ms,
                },
                "meta": {"llm_timing_mode": "blocking_ttft_equals_ttlt"},
            }
            sources = [chunk.content for chunk in context_chunks]

        explain_ms = 0.0
        cite_ms = 0.0
        entities_used: List[str] = []
        resp_kwargs: Dict[str, Any] = {
            "document_id": document_id,
            "query": query,
            "answer": answer,
            "sources": sources,
            "skill": skill,
            "model_used": model_used,
            "conversation_id": conversation_id,
        }

        if settings.EXPLAINABILITY_ENABLED:
            from src.explainability.builder import ExplainabilityBuilder

            t_explain = time.perf_counter()
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
            explain_ms = (time.perf_counter() - t_explain) * 1000.0
            t_cite = time.perf_counter()
            # Citation serialization is part of explainability envelope; measure dict build
            chunk_dicts = [c.to_dict() for c in envelope.retrieved_chunks]
            cite_ms = (time.perf_counter() - t_cite) * 1000.0
            entities_used = list(envelope.entities_used)
            resp_kwargs.update(
                {
                    "confidence": envelope.confidence,
                    "knowledge_sources": envelope.knowledge_sources,
                    "retrieved_chunks": chunk_dicts,
                    "entities_used": envelope.entities_used,
                    "reasoning_path": envelope.reasoning_path,
                    "missing_context": envelope.missing_context,
                    "model": envelope.model.to_dict() if envelope.model else None,
                    "routing_ref": envelope.routing_ref,
                }
            )

        total_ms = (time.perf_counter() - t_request) * 1000.0
        latency = merge_latency(
            retrieval_latency,
            assemble_latency,
            llm_latency,
            {
                "stages_ms": {
                    STAGE_EXPLAINABILITY: round(explain_ms, 3),
                    STAGE_CITATIONS: round(cite_ms, 3),
                },
                "meta": {},
            },
            total_ms=total_ms,
        )
        if STAGE_CONTEXT_ASSEMBLE not in (latency.get("stages_ms") or {}):
            latency.setdefault("stages_ms", {})[STAGE_CONTEXT_ASSEMBLE] = 0.0

        violations = snapshot_violations()
        resources_end = sample_resources()
        latency.setdefault("meta", {})
        latency["meta"].update(
            {
                "document_id": document_id,
                "pipeline_validation": {
                    "ingest_ops_on_query_path": violations,
                    "clean": len(violations) == 0,
                },
                "resources_start": resources_start,
                "resources_end": resources_end,
                "active_threads": threading.active_count(),
            }
        )
        # Promote nested LLM meta if present
        llm_meta = (llm_latency.get("meta") or {}) if isinstance(llm_latency, dict) else {}
        for key in ("nim", "prompt", "llm_timing_mode"):
            if key in llm_meta and key not in latency["meta"]:
                latency["meta"][key] = llm_meta[key]
        attach_resource_snapshot(latency, label="end")
        log_query_latency(document_id=document_id, query=query, latency=latency)
        resp_kwargs["latency"] = latency

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
        log.error(f"Error during RAG generation: {e}")
        raise HTTPException(status_code=500, detail="Error generating answer.")
    finally:
        end_query_path()


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
def get_dashboard_stats(
    current_user: Dict[str, Any] = Depends(get_current_user),
    range: str = Query("30d"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    """
    Get aggregated statistics for the dashboard (current user only).

    Includes a static ``methodology`` note for the carbon comparison visualization
    layer. Per-document ``comparison_models`` / ``summary_cards`` are attached on
    ``GET /job-result/{job_id}`` from already-computed ``carbon_data``.

    Actual = sum of green-agent costs from completed jobs.
    Baseline = ChatGPT/frontier published estimate scaled by document chunks.
    """
    try:
        from src.core.frontier_carbon_compare import METHODOLOGY_TEXT

        stats = storage.get_dashboard_stats(
            user_id=int(current_user["id"]),
            range_key=range,
            start_date=start_date,
            end_date=end_date,
        )
        if isinstance(stats, dict):
            stats = dict(stats)
            stats.setdefault("methodology", METHODOLOGY_TEXT)
            stats.setdefault("comparison_models", [])
            stats.setdefault("summary_cards", None)
        return stats
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
