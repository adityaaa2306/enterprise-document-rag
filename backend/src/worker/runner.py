"""Execute a claimed job by invoking the existing agentic graph (unchanged)."""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, Optional

from src.core import job_status as job_status_mod
from src.core.config import settings
from src.core.intelligent_router import normalize_routing_preference
from src.core.orchestrator import agentic_graph
from src.core.processing_insights import build_processing_insights
from src.db import jobs as job_store
from src.memory import storage
from src.storage import get_object_storage

log = logging.getLogger("worker.runner")

SCRATCH_DIR = "temp_uploads"


def process_claimed_job(job: Dict[str, Any], *, worker_id: str) -> None:
    """
    Run the pipeline for an already-claimed job.

    Expects job dict with job_id; loads document storage metadata from DB.
    Does not modify CRE / router / agents — only invokes agentic_graph.

    Guarantees a terminal transition out of ``processing``:
      processing → complete  (success)
      processing → pending   (retryable failure)
      processing → error     (exhausted retries / hard failure)
    """
    job_id = str(job["job_id"])
    document_id = job_id
    mode = normalize_routing_preference(job.get("job_mode") or "automatic")
    user_id = job.get("user_id")
    display_name = job.get("filename") or "upload.bin"
    max_runtime = float(getattr(settings, "JOB_MAX_RUNTIME_SEC", 600.0) or 600.0)

    # Prefer content_type from document row when available
    content_type = "application/octet-stream"
    try:
        from src.db.models import DocumentModel
        from src.db.session import get_session

        db = get_session()
        try:
            doc = db.get(DocumentModel, document_id)
            if doc is not None:
                if doc.original_filename:
                    display_name = doc.original_filename
                if doc.content_type:
                    content_type = doc.content_type
        finally:
            db.close()
    except Exception as e:
        log.warning(f"Could not load document metadata for {document_id}: {e}")

    os.makedirs(SCRATCH_DIR, exist_ok=True)
    scratch_path = os.path.join(SCRATCH_DIR, f"{job_id}_{display_name}")
    abandoned = threading.Event()
    reached_terminal = False

    try:
        storage_key = storage.get_document_storage_key(document_id)
        if not storage_key:
            raise RuntimeError(f"No storage_key for document {document_id}")

        log.info("Job %s: claimed → processing", job_id)
        job_store.upsert_job(
            job_id,
            status=job_status_mod.STATUS_PROCESSING,
            progress=5.0,
            message="Job initialized. Preparing agentic graph...",
            understanding="pending" if settings.ENABLE_UNDERSTANDING else "skipped",
            filename=display_name,
            job_mode=mode,
            user_id=user_id,
            claimed_by=worker_id,
            heartbeat_at=job_store._now(),
            error_detail=None,
        )
        if user_id is not None:
            storage.ensure_document_owner(document_id, int(user_id))

        job_store.touch_job_heartbeat(job_id, worker_id)

        store = get_object_storage()
        store.download_to_path(storage_key, scratch_path)

        initial_state = {
            "file_path": scratch_path,
            "file_type": content_type,
            "job_id": job_id,
            "document_id": document_id,
            "job_mode": mode,
            "final_summary": "",
            "total_chunks": 0,
            "chunks_escalated": 0,
            "carbon_report": {},
            "model_usage_chars": {"light": 0, "medium": 0, "large": 0},
        }

        log.info(
            "Job %s: Invoking Agentic Graph (worker=%s, max_runtime=%.0fs)...",
            job_id,
            worker_id,
            max_runtime,
        )
        job_store.set_progress(job_id, 10.0, "Running agentic pipeline...")

        # Keep job + worker heartbeats fresh during long NIM / graph calls,
        # but stop heartbeating (and fail) if wall-clock budget is exceeded.
        stop_hb = threading.Event()
        started = time.monotonic()
        runtime_exceeded = threading.Event()

        def _heartbeat_loop() -> None:
            interval = max(5.0, float(settings.WORKER_HEARTBEAT_INTERVAL_SEC))
            while not stop_hb.wait(interval):
                if time.monotonic() - started >= max_runtime:
                    runtime_exceeded.set()
                    log.error(
                        "Job %s: wall-clock budget exceeded (%.0fs) — stopping heartbeats",
                        job_id,
                        max_runtime,
                    )
                    return
                try:
                    job_store.touch_job_heartbeat(job_id, worker_id)
                except Exception as he:
                    log.warning(f"Job {job_id}: heartbeat failed: {he}")

        hb_thread = threading.Thread(
            target=_heartbeat_loop,
            name=f"hb-{job_id[:8]}",
            daemon=True,
        )
        hb_thread.start()

        result_box: Dict[str, Any] = {}
        error_box: Dict[str, Exception] = {}

        def _invoke_graph() -> None:
            try:
                result_box["state"] = agentic_graph.invoke(initial_state)
            except Exception as ge:
                error_box["err"] = ge

        graph_thread = threading.Thread(
            target=_invoke_graph,
            name=f"graph-{job_id[:8]}",
            daemon=True,
        )
        try:
            graph_thread.start()
            # Poll join so we can react to wall-clock / abandon quickly
            deadline = started + max_runtime
            while graph_thread.is_alive():
                remaining = deadline - time.monotonic()
                if remaining <= 0 or runtime_exceeded.is_set():
                    abandoned.set()
                    raise TimeoutError(
                        f"Job exceeded max runtime of {max_runtime:.0f}s "
                        f"(likely hung external API call). Marking failed."
                    )
                graph_thread.join(timeout=min(5.0, max(0.1, remaining)))

            if "err" in error_box:
                raise error_box["err"]
            if "state" not in result_box:
                raise RuntimeError("Agentic graph finished without a result state")
            final_state = result_box["state"]
        finally:
            stop_hb.set()
            hb_thread.join(timeout=2.0)

        if abandoned.is_set():
            # Late completion after we already decided to fail — do not overwrite.
            log.warning("Job %s: ignoring late graph result after abandon", job_id)
            if not reached_terminal:
                job_store.fail_or_retry_job(
                    job_id,
                    error="Job abandoned after runtime limit; late result ignored.",
                    worker_id=worker_id,
                )
                reached_terminal = True
            return

        log.info("Job %s: pipeline finished → attaching result / complete", job_id)

        raw_carbon = dict(final_state.get("carbon_report") or {})
        carbon_fields = {
            "carbon_saved_grams": float(raw_carbon.get("carbon_saved_grams") or 0.0),
            "message": str(raw_carbon.get("message") or ""),
            "total_chunks": int(raw_carbon.get("total_chunks") or 0),
            "chunks_escalated": int(raw_carbon.get("chunks_escalated") or 0),
            "local_grid_gco2_kwh": float(raw_carbon.get("local_grid_gco2_kwh") or 0.0),
            "remote_grid_gco2_kwh": raw_carbon.get("remote_grid_gco2_kwh"),
            "compute_location": str(raw_carbon.get("compute_location") or "unknown"),
            "baseline_cost_gco2e": float(raw_carbon.get("baseline_cost_gco2e") or 0.0),
            "actual_cost_gco2e": float(raw_carbon.get("actual_cost_gco2e") or 0.0),
            "efficiency_percent": float(raw_carbon.get("efficiency_percent") or 0.0),
        }

        insights = build_processing_insights(
            routing_decision=final_state.get("routing_decision"),
            cre_result=final_state.get("cre_result"),
            carbon_report=raw_carbon,
            validation_verdict=final_state.get("validation_verdict"),
            job_mode=mode,
            latency_ms=final_state.get("job_latency_ms"),
        )

        understanding_status = "pending" if settings.ENABLE_UNDERSTANDING else "skipped"
        job_store.upsert_job(
            job_id,
            status=job_status_mod.STATUS_COMPLETE,
            progress=100.0,
            message="Job complete. Results are ready.",
            understanding=understanding_status,
            result={
                "document_id": document_id,
                "filename": display_name,
                "final_summary": final_state["final_summary"],
                "carbon_data": carbon_fields,
                "job_id": job_id,
                "processing_insights": insights,
            },
            routing_decision=final_state.get("routing_decision"),
            latency_ms=final_state.get("job_latency_ms"),
            carbon_saved_grams=carbon_fields.get("carbon_saved_grams"),
            user_id=user_id,
            claimed_by=None,
            heartbeat_at=None,
            error_detail=None,
        )
        reached_terminal = True
        log.info("Job %s: processing → complete", job_id)

        if settings.ENABLE_UNDERSTANDING:
            def _bg():
                try:
                    from src.agents.understanding_agent import run_understanding_for_document

                    run_understanding_for_document(document_id, job_id=job_id)
                except Exception as ue:
                    log.error(f"Async understanding failed for {document_id}: {ue}")
                    job_store.set_understanding(job_id, "failed")

            threading.Thread(target=_bg, daemon=True, name=f"understand-{job_id[:8]}").start()

    except Exception as e:
        abandoned.set()
        log.error("Job %s FAILED: %s", job_id, e)
        try:
            job_store.fail_or_retry_job(job_id, error=str(e), worker_id=worker_id)
            reached_terminal = True
        except Exception as fe:
            log.exception("Job %s: fail_or_retry_job itself failed: %s", job_id, fe)
            # Last-resort terminal write so polling can stop.
            try:
                job_store.upsert_job(
                    job_id,
                    status=job_status_mod.STATUS_ERROR,
                    progress=100.0,
                    message=str(e),
                    error_detail=str(e),
                    claimed_at=None,
                    claimed_by=None,
                    heartbeat_at=None,
                )
                reached_terminal = True
            except Exception:
                log.exception("Job %s: could not write terminal error status", job_id)
        raise
    finally:
        if not reached_terminal:
            # Safety net: never leave the job permanently in processing.
            try:
                current = job_store.get_job(job_id) or {}
                if not job_status_mod.is_terminal(current.get("status")):
                    log.error(
                        "Job %s: safety net — still non-terminal (%s); marking error",
                        job_id,
                        current.get("status"),
                    )
                    job_store.upsert_job(
                        job_id,
                        status=job_status_mod.STATUS_ERROR,
                        progress=100.0,
                        message="Job ended without a terminal status (internal safety net).",
                        error_detail="non_terminal_exit",
                        claimed_at=None,
                        claimed_by=None,
                        heartbeat_at=None,
                    )
            except Exception as se:
                log.exception("Job %s: safety-net status write failed: %s", job_id, se)
        try:
            if os.path.isfile(scratch_path):
                os.remove(scratch_path)
        except OSError:
            pass
