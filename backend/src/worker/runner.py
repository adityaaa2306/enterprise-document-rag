"""Execute a claimed job by invoking the existing agentic graph (unchanged)."""
from __future__ import annotations

import logging
import os
import threading
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
    """
    job_id = str(job["job_id"])
    document_id = job_id
    mode = normalize_routing_preference(job.get("job_mode") or "automatic")
    user_id = job.get("user_id")
    display_name = job.get("filename") or "upload.bin"

    storage_key = storage.get_document_storage_key(document_id)
    if not storage_key:
        raise RuntimeError(f"No storage_key for document {document_id}")

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

    try:
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

        log.info(f"Job {job_id}: Invoking Agentic Graph (worker={worker_id})...")
        job_store.set_progress(job_id, 10.0, "Running agentic pipeline...")
        final_state = agentic_graph.invoke(initial_state)
        log.info(f"Job {job_id} completed successfully.")

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
        )

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
        log.error(f"Job {job_id} FAILED: {e}")
        job_store.fail_or_retry_job(job_id, error=str(e), worker_id=worker_id)
        raise
    finally:
        try:
            if os.path.isfile(scratch_path):
                os.remove(scratch_path)
        except OSError:
            pass
