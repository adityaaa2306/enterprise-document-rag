"""
Agentic Orchestrator — Capability-first routing pipeline.

Upload → Triage → Feature Extraction → CRE → Intelligent Router →
Map Summarize → Quality Validation → (+1 tier escalate if needed) →
Compile → Store → Carbon/Telemetry
"""
from __future__ import annotations

import logging
import concurrent.futures
import time
from typing import TypedDict, List, Dict, Any, Optional

from langgraph.graph import StateGraph, END

from src.agents import triage, models, feature_extraction, quality_validation
from src.memory import storage
from src.memory.document_ids import align_chunks_to_document_id
from src.chunking import ChunkingService
from src.core import scheduler, cre, intelligent_router
from src.core.config import settings
from src.core import job_status as job_status_mod
from src.monitoring import metrics, routing_telemetry
from src.monitoring.ingestion_latency import (
    IngestionLatencyTracker,
    STAGE_COMPILE,
    STAGE_CRE_ROUTE,
    STAGE_ESCALATE,
    STAGE_FEATURE_EXTRACT,
    STAGE_FINALIZE,
    STAGE_MAP_SUMMARIZE,
    STAGE_STORE,
    STAGE_TRIAGE,
    STAGE_VALIDATE,
    format_latency_table,
    log_ingestion_latency,
)
from src.db import jobs as job_store

log = logging.getLogger(__name__)

# Backward-compatible alias — durable when PERSIST_JOBS_TO_DB is enabled
JOB_STATUSES = job_store.JOB_STATUSES


class AgentState(TypedDict, total=False):
    job_id: str
    document_id: str
    file_path: str
    file_type: str
    job_mode: str

    chunks: List[Any]
    summaries: List[str]
    final_summary: str

    total_chunks: int
    chunks_escalated: int
    carbon_report: Dict[str, Any]
    model_usage_chars: Dict[str, int]
    models_used: List[str]

    # CRE / routing
    features: Dict[str, Any]
    cre_result: Dict[str, Any]
    routing_decision: Dict[str, Any]
    validation_verdict: Dict[str, Any]
    escalation_count: int
    accept_with_warning: bool
    job_started_ms: float
    triage_meta: Dict[str, Any]
    chunk_parents: List[Any]
    # Diagnostic only — stage + per-chunk timings
    ingestion_latency: Dict[str, Any]


def _set_progress(job_id: str, progress: float, message: str) -> None:
    job_store.set_progress(job_id, progress, message)


def _get_latency(state: AgentState) -> IngestionLatencyTracker:
    """Rebuild tracker from state dict (LangGraph may not preserve the object)."""
    raw = state.get("ingestion_latency")
    if isinstance(raw, IngestionLatencyTracker):
        return raw
    lat = IngestionLatencyTracker(job_id=state.get("job_id") or "")
    if isinstance(raw, dict):
        lat.stages.update(raw.get("stages_ms") or {})
        lat.meta.update(raw.get("meta") or {})
        lat.chunk_calls = list(raw.get("chunk_calls") or [])
        lat.pool_samples = list(raw.get("pool_samples") or [])
        lat._peak_active = int(raw.get("pool_peak_active") or 0)
        # Restore monotonic origin from elapsed_so_far so total_ms stays correct
        elapsed = raw.get("_elapsed_so_far_ms")
        if elapsed is not None:
            lat._t0 = time.perf_counter() - (float(elapsed) / 1000.0)
    return lat


def _persist_latency(lat: IngestionLatencyTracker) -> Dict[str, Any]:
    return lat.as_dict()


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def start_job(state: AgentState) -> AgentState:
    job_id = state["job_id"]
    log.info(f"Job {job_id}: [1] Starting capability-routed job (mode={state.get('job_mode')}).")
    state["model_usage_chars"] = {"light": 0, "medium": 0, "large": 0}
    state["models_used"] = []
    state["escalation_count"] = 0
    state["accept_with_warning"] = False
    state["chunks_escalated"] = 0
    state["job_started_ms"] = time.time() * 1000
    state["ingestion_latency"] = IngestionLatencyTracker(job_id=job_id).as_dict()

    job_store.upsert_job(
        job_id,
        status="processing",
        progress=5.0,
        message="Starting job...",
    )
    return state


def triage_document(state: AgentState) -> Dict[str, Any]:
    job_id = state["job_id"]
    document_id = state.get("document_id") or job_id
    log.info(f"Job {job_id}: [2] Triaging document...")
    _set_progress(job_id, 12.0, "Triage: analyzing document layout...")
    lat = _get_latency(state)

    with lat.stage(STAGE_TRIAGE):
        raw_chunks = triage.triage_document(
            file_path=state["file_path"],
            file_type=state["file_type"],
            strategy=settings.TRIAGE_STRATEGY,
        )
        if not raw_chunks:
            raise ValueError("Triage returned no chunks. Cannot proceed.")

        triage_meta: Dict[str, Any] = {
            "strategy": settings.TRIAGE_STRATEGY,
            "adaptive": False,
        }
        chunk_parents: List[Any] = []

        if settings.USE_ADAPTIVE_CHUNKING:
            _set_progress(job_id, 14.0, "Adaptive chunking...")
            embed_fn = None
            # Optional NIM similarity; fall back to lexical inside ChunkingService
            if models.get_nim_client() is not None:
                try:
                    embed_fn = models.embed_texts
                except Exception:
                    embed_fn = None
            chunks, parents, meta = ChunkingService(embed_fn=embed_fn).build(
                raw_chunks, document_id=document_id
            )
            chunk_parents = parents
            triage_meta.update(meta)
            triage_meta["raw_triage_chunks"] = len(raw_chunks)
            log.info(
                f"Job {job_id}: Adaptive chunking {len(raw_chunks)} → {len(chunks)} "
                f"({meta.get('section_count', 0)} sections)."
            )
        else:
            chunks = align_chunks_to_document_id(document_id, raw_chunks)
            log.info(f"Job {job_id}: Triage complete (adaptive off). {len(chunks)} chunks.")

        if not chunks:
            raise ValueError("Chunking produced no chunks. Cannot proceed.")

    lat.add_meta(total_chunks=len(chunks), raw_triage_chunks=len(raw_chunks))
    return {
        "chunks": chunks,
        "total_chunks": len(chunks),
        "triage_meta": triage_meta,
        "chunk_parents": chunk_parents,
        "ingestion_latency": _persist_latency(lat),
    }


def extract_features_node(state: AgentState) -> Dict[str, Any]:
    job_id = state["job_id"]
    log.info(f"Job {job_id}: [3] Feature Extraction Agent...")
    _set_progress(job_id, 20.0, "Extracting capability features...")
    lat = _get_latency(state)

    triage_meta = state.get("triage_meta") or {"strategy": settings.TRIAGE_STRATEGY}
    with lat.stage(STAGE_FEATURE_EXTRACT):
        try:
            features = feature_extraction.extract_features(state["chunks"], triage_meta)
            log.info(
                "Job %s: feature extraction complete via %s",
                job_id,
                (features or {}).get("classifier_method"),
            )
        except Exception as e:
            # Optional metadata — never leave the job stuck; continue with defaults.
            log.warning(
                "Job %s: feature extraction failed (%s) → using default metadata",
                job_id,
                e,
            )
            _set_progress(
                job_id,
                22.0,
                f"Feature extraction failed ({type(e).__name__}); using default metadata...",
            )
            features = feature_extraction.default_features(
                state["chunks"], triage_meta, reason=type(e).__name__
            )
    lat.add_meta(
        feature_classifier=(features or {}).get("classifier_method"),
        document_type=(features or {}).get("document_type"),
    )
    return {"features": features, "ingestion_latency": _persist_latency(lat)}


def cre_and_route(state: AgentState) -> Dict[str, Any]:
    job_id = state["job_id"]
    mode = (state.get("job_mode") or "automatic").lower()
    log.info(f"Job {job_id}: [4] CRE + Intelligent Router (preference={mode})...")
    _set_progress(job_id, 28.0, "Computing capability requirement & routing...")
    lat = _get_latency(state)

    with lat.stage(STAGE_CRE_ROUTE):
        cre_result = cre.compute_crs(state["features"])
        decision = intelligent_router.route(cre_result, state["features"], mode=mode)

    routing_summary = (
        f"tier={decision.tier} model={decision.selected_model} "
        f"crs={cre_result.crs:.3f} min_tier={cre_result.min_tier} "
        f"compile={decision.compile_tier} reason={decision.reason_summary}"
    )
    lat.add_meta(
        routing_summary=routing_summary,
        selected_model=decision.selected_model,
        tier=decision.tier,
        crs=cre_result.crs,
        min_tier=cre_result.min_tier,
        compile_tier=decision.compile_tier,
        fallbacks=list(decision.fallbacks or []),
        cre_route_ms=lat.stages.get(STAGE_CRE_ROUTE),
    )
    log.info(
        "Job %s: routing decision in %.1fms → %s",
        job_id,
        lat.stages.get(STAGE_CRE_ROUTE) or 0.0,
        routing_summary,
    )
    return {
        "cre_result": cre_result.to_dict(),
        "routing_decision": decision.to_dict(),
        "ingestion_latency": _persist_latency(lat),
    }


def map_summarize_routed(state: AgentState) -> Dict[str, Any]:
    job_id = state["job_id"]
    decision = state["routing_decision"]
    tier = decision["tier"]
    chain = decision.get("fallbacks") or [decision["selected_model"]]
    lat = _get_latency(state)

    # ONE-SHOT status at stage entry (not a heartbeat). Chunk progress updates
    # only fire when as_completed yields — so a long first NIM call leaves this
    # message unchanged for minutes.
    log.info(f"Job {job_id}: [5] Map summarize with tier={tier} model={chain[0]}")
    _set_progress(job_id, 35.0, f"Summarizing chunks with {tier} tier...")

    chunks = state["chunks"]
    total = state["total_chunks"]
    summaries: List[str] = [""] * len(chunks)
    max_workers = max(1, int(getattr(settings, "MAP_MAX_WORKERS", 3) or 3))
    lat.add_meta(map_max_workers=max_workers, map_tier=tier, map_model_chain=list(chain))

    submit_times: Dict[int, float] = {}
    stage_t0 = time.perf_counter()

    def _run(idx_chunk):
        idx, chunk = idx_chunk
        queue_ms = (time.perf_counter() - submit_times[idx]) * 1000.0
        active = lat.worker_enter()
        log.info(
            "ingest_pool job_id=%s event=worker_enter chunk=%s active=%s/%s queue_ms=%.1f",
            job_id,
            idx,
            active,
            max_workers,
            queue_ms,
        )
        call_meta: Dict[str, Any] = {}
        try:
            text = models.run_tier_summarizer(
                chunk.content,
                state,
                tier=tier,
                model_ids=chain,
                call_meta=call_meta,
            )
            success = bool(call_meta.get("success", True)) and not str(text).startswith(
                ("Error:", "Summary generation failed")
            )
            if "success" not in call_meta:
                call_meta["success"] = success
            lat.record_chunk_call(
                {
                    "chunk_index": idx,
                    "tier": tier,
                    "model_id": call_meta.get("model_id") or chain[0],
                    "queue_ms": round(queue_ms, 1),
                    "call_ms": round(float(call_meta.get("call_ms") or 0.0), 1),
                    "success": bool(call_meta.get("success")),
                    "retry_count": int(call_meta.get("retry_count") or 0),
                    "attempt_count": int(call_meta.get("attempt_count") or 0),
                    "http_status": call_meta.get("http_status"),
                    "attempts": call_meta.get("attempts") or [],
                    "phase": "map",
                }
            )
            return idx, text
        finally:
            active_after = lat.worker_exit()
            log.info(
                "ingest_pool job_id=%s event=worker_exit chunk=%s active=%s/%s",
                job_id,
                idx,
                active_after,
                max_workers,
            )

    with lat.stage(STAGE_MAP_SUMMARIZE):
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for i, c in enumerate(chunks):
                submit_times[i] = time.perf_counter()
                futures.append(executor.submit(_run, (i, c)))
            done = 0
            for fut in concurrent.futures.as_completed(futures):
                idx, text = fut.result()
                summaries[idx] = text
                done += 1
                progress = 35.0 + (done / max(total, 1)) * 25.0
                _set_progress(job_id, progress, f"Summarizing... ({done}/{total})")

    lat.add_meta(
        map_wall_ms=round((time.perf_counter() - stage_t0) * 1000.0, 1),
        map_first_complete_note=(
            "UI stays on 'Summarizing chunks with {tier} tier...' until the first "
            "future completes; that message is set once at stage start, not a heartbeat."
        ),
    )
    return {"summaries": summaries, "ingestion_latency": _persist_latency(lat)}


def validate_map(state: AgentState) -> Dict[str, Any]:
    job_id = state["job_id"]
    log.info(f"Job {job_id}: [6] Quality Validation (map)...")
    _set_progress(job_id, 65.0, "Validating summary quality...")
    lat = _get_latency(state)

    with lat.stage(STAGE_VALIDATE):
        verdict = quality_validation.validate_chunks(state["chunks"], state["summaries"])
    log.info(
        f"Job {job_id}: QVA map passed={verdict.passed} conf={verdict.confidence} "
        f"codes={verdict.codes}"
    )
    return {
        "validation_verdict": verdict.to_dict(),
        "ingestion_latency": _persist_latency(lat),
    }


def should_escalate(state: AgentState) -> str:
    verdict = state.get("validation_verdict") or {}
    esc = int(state.get("escalation_count") or 0)
    max_esc = settings.QVA_MAX_ESCALATIONS

    if verdict.get("passed"):
        log.info(f"Job {state['job_id']}: Validation passed → compile")
        return "compile"

    if esc >= max_esc:
        log.info(
            f"Job {state['job_id']}: Validation failed but escalation budget exhausted → compile with warning"
        )
        return "compile_warn"

    log.info(f"Job {state['job_id']}: Validation failed → escalate +1 tier")
    return "escalate"


def escalate_once(state: AgentState) -> Dict[str, Any]:
    """Confidence-based escalation: bump exactly one tier and re-summarize."""
    job_id = state["job_id"]
    verdict = state.get("validation_verdict") or {}
    codes = verdict.get("codes") or ["validation_failed"]
    lat = _get_latency(state)

    raw = dict(state["routing_decision"])
    # Reconstruct dataclass safely
    fields = intelligent_router.RoutingDecision.__dataclass_fields__
    kwargs = {k: raw.get(k) for k in fields if k in raw}
    kwargs.setdefault("escalations", list(raw.get("escalations") or []))
    decision = intelligent_router.RoutingDecision(**kwargs)
    decision = intelligent_router.escalate_decision(decision, codes)
    esc_count = int(state.get("escalation_count") or 0) + 1

    details = verdict.get("details") or {}
    failed_idx = list(details.get("failed_indices") or [])
    if not failed_idx:
        failed_idx = list(range(len(state["chunks"])))

    # Prefer worst chunks first (lowest confidence), then cap — lexical QVA can
    # mark nearly every abstractive summary as failed and drown the heavy tier.
    confidences = details.get("chunk_confidences") or []
    if confidences and len(confidences) == len(state.get("summaries") or []):
        failed_idx = sorted(
            failed_idx,
            key=lambda i: confidences[i] if 0 <= i < len(confidences) else 0.0,
        )
    max_esc_chunks = max(1, int(getattr(settings, "QVA_MAX_ESCALATE_CHUNKS", 8) or 8))
    if len(failed_idx) > max_esc_chunks:
        log.info(
            "Job %s: capping escalate from %s → %s worst chunks (QVA_MAX_ESCALATE_CHUNKS)",
            job_id,
            len(failed_idx),
            max_esc_chunks,
        )
        failed_idx = failed_idx[:max_esc_chunks]

    log.info(
        f"Job {job_id}: [6b] Escalating {len(failed_idx)} chunks to {decision.tier}"
    )
    # Distinct message from map_summarize intro — not a re-emit of map status.
    _set_progress(
        job_id, 70.0, f"Escalating to {decision.tier} tier ({len(failed_idx)} chunks)..."
    )

    summaries = list(state["summaries"])
    chain = decision.fallbacks
    tier = decision.tier
    max_workers = max(1, int(getattr(settings, "MAP_MAX_WORKERS", 3) or 3))
    submit_times: Dict[int, float] = {}
    total_esc = len(failed_idx)
    done = 0

    def _run(i):
        queue_ms = (time.perf_counter() - submit_times[i]) * 1000.0
        active = lat.worker_enter()
        log.info(
            "ingest_pool job_id=%s event=escalate_enter chunk=%s active=%s/%s queue_ms=%.1f",
            job_id,
            i,
            active,
            max_workers,
            queue_ms,
        )
        call_meta: Dict[str, Any] = {}
        try:
            chunk = state["chunks"][i]
            text = models.run_tier_summarizer(
                chunk.content, state, tier=tier, model_ids=chain, call_meta=call_meta
            )
            lat.record_chunk_call(
                {
                    "chunk_index": i,
                    "tier": tier,
                    "model_id": call_meta.get("model_id") or (chain[0] if chain else None),
                    "queue_ms": round(queue_ms, 1),
                    "call_ms": round(float(call_meta.get("call_ms") or 0.0), 1),
                    "success": bool(call_meta.get("success", True)),
                    "retry_count": int(call_meta.get("retry_count") or 0),
                    "attempt_count": int(call_meta.get("attempt_count") or 0),
                    "http_status": call_meta.get("http_status"),
                    "attempts": call_meta.get("attempts") or [],
                    "phase": "escalate",
                }
            )
            return i, text
        finally:
            lat.worker_exit()

    with lat.stage(STAGE_ESCALATE):
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for i in failed_idx:
                if i >= len(summaries):
                    continue
                submit_times[i] = time.perf_counter()
                futures.append(executor.submit(_run, i))
            for fut in concurrent.futures.as_completed(futures):
                i, text = fut.result()
                summaries[i] = text
                done += 1
                progress = 70.0 + (10.0 * done / max(total_esc, 1))
                _set_progress(
                    job_id,
                    progress,
                    f"Escalating ({decision.tier})... ({done}/{total_esc})",
                )

    new_verdict = quality_validation.validate_chunks(state["chunks"], summaries)
    lat.add_meta(
        escalated_chunks=len(failed_idx),
        escalate_tier=tier,
        escalate_model_chain=list(chain or []),
    )

    return {
        "routing_decision": decision.to_dict(),
        "summaries": summaries,
        "escalation_count": esc_count,
        "chunks_escalated": len(failed_idx),
        "validation_verdict": new_verdict.to_dict(),
        "accept_with_warning": not new_verdict.passed,
        "ingestion_latency": _persist_latency(lat),
    }


def mark_warning(state: AgentState) -> Dict[str, Any]:
    return {"accept_with_warning": True}


def reduce_compile(state: AgentState) -> Dict[str, Any]:
    job_id = state["job_id"]
    decision = state["routing_decision"]
    compile_chain = decision.get("compile_fallbacks") or settings.heavy_models()
    lat = _get_latency(state)

    log.info(
        f"Job {job_id}: [7] Compile with tier={decision.get('compile_tier')} "
        f"model={compile_chain[0]}"
    )
    _set_progress(job_id, 82.0, "Compiling executive summary...")

    with lat.stage(STAGE_COMPILE):
        # Pass the list so compile can hierarchically batch large docs and skip
        # failed chunk summaries. Cross-tier fallback lives in models.run_compile_with_models.
        final_summary = models.run_compile_with_models(
            state["summaries"], state, compile_chain
        )
        final_verdict = quality_validation.validate_final(state["summaries"], final_summary)
    accept_warn = bool(state.get("accept_with_warning")) or not final_verdict.passed

    return {
        "final_summary": final_summary,
        "validation_verdict": final_verdict.to_dict(),
        "accept_with_warning": accept_warn,
        "ingestion_latency": _persist_latency(lat),
    }


def store_for_rag(state: AgentState) -> Dict[str, Any]:
    job_id = state["job_id"]
    log.info(f"Job {job_id}: [8] Storing for RAG...")
    _set_progress(job_id, 90.0, "Indexing for search...")
    lat = _get_latency(state)

    with lat.stage(STAGE_STORE):
        try:
            storage.store_document_data(
                job_id=job_id,
                summary=state["final_summary"],
                chunks=state["chunks"],
                routing_decision=state.get("routing_decision"),
            )
            log.info("Job %s: stored in Chroma / document store", job_id)
        except Exception as e:
            # Indexing failure should not orphan the job in processing — surface as
            # a hard failure so the runner marks error/retry.
            log.error("Job %s: store_for_rag failed: %s", job_id, e)
            raise
    return {"ingestion_latency": _persist_latency(lat)}


def finalize_metrics(state: AgentState) -> Dict[str, Any]:
    job_id = state["job_id"]
    log.info(f"Job {job_id}: [9] Carbon + telemetry...")
    _set_progress(job_id, 98.0, "Recording metrics...")
    lat = _get_latency(state)

    with lat.stage(STAGE_FINALIZE):
        report = scheduler.calculate_carbon_savings(job_id=job_id, state=state)

        # Attach routing explainability into carbon/message side-channel
        decision = state.get("routing_decision") or {}
        cre_result = state.get("cre_result") or {}
        report = {
            **report,
            "routing": {
                "selected_model": decision.get("selected_model"),
                "tier": decision.get("tier"),
                "crs": cre_result.get("crs"),
                "reason": decision.get("reason_summary"),
                "escalations": decision.get("escalations"),
                "accept_with_warning": state.get("accept_with_warning", False),
            },
        }

        metrics.log_job_metrics(job_id, report, state)

        latency = None
        if state.get("job_started_ms"):
            latency = (time.time() * 1000) - float(state["job_started_ms"])

        routing_telemetry.log_job_routing(
            job_id=job_id,
            mode=state.get("job_mode") or "automatic",
            features=state.get("features") or {},
            cre=cre_result,
            decision=decision,
            validation=state.get("validation_verdict"),
            carbon_report=report,
            latency_ms=latency,
        )

        storage.store_document_data(
            job_id=job_id,
            summary=state["final_summary"],
            chunks=[],
            carbon_meta=report,
            routing_decision=decision or None,
        )

    ingestion_latency = lat.finish()
    log_ingestion_latency(job_id, ingestion_latency)
    table = format_latency_table(ingestion_latency)
    for line in table.splitlines():
        log.info("Job %s: %s", job_id, line)

    # Persist compact latency JSON for offline analysis
    try:
        from pathlib import Path
        import json

        out_dir = Path(settings.VECTOR_DB_PATH) / "ingest_latency"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{job_id}.json"
        # Drop bulky attempt arrays in the on-disk summary? Keep full for diagnostics.
        out_path.write_text(json.dumps(ingestion_latency, indent=2), encoding="utf-8")
        log.info("Job %s: wrote ingest latency → %s", job_id, out_path)
    except Exception as e:
        log.warning("Job %s: failed to write ingest latency file: %s", job_id, e)

    job_store.upsert_job(
        job_id,
        progress=100.0,
        message=(
            "Job metrics recorded (accepted with warning). Finalizing results..."
            if state.get("accept_with_warning")
            else "Job metrics recorded. Finalizing results..."
        ),
        # Do not mark terminal "complete" here — the API background runner attaches
        # the SummaryResponse ``result`` payload and then sets STATUS_COMPLETE.
        status=job_status_mod.STATUS_PROCESSING,
        routing_decision=decision or None,
        crs=cre_result.get("crs"),
        selected_model=decision.get("selected_model"),
        latency_ms=latency,
        carbon_saved_grams=(report or {}).get("carbon_saved_grams"),
    )

    log.info(f"Job {job_id}: Done. CRS={cre_result.get('crs')} model={decision.get('selected_model')}")
    return {
        "carbon_report": report,
        "job_latency_ms": latency,
        "ingestion_latency": ingestion_latency,
    }


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

log.info("Building Capability-Routed Agentic Graph...")

workflow = StateGraph(AgentState)

workflow.add_node("start_job", start_job)
workflow.add_node("triage_document", triage_document)
workflow.add_node("extract_features", extract_features_node)
workflow.add_node("cre_and_route", cre_and_route)
workflow.add_node("map_summarize", map_summarize_routed)
workflow.add_node("validate_map", validate_map)
workflow.add_node("escalate_once", escalate_once)
workflow.add_node("mark_warning", mark_warning)
workflow.add_node("reduce_compile", reduce_compile)
workflow.add_node("store_for_rag", store_for_rag)
workflow.add_node("finalize_metrics", finalize_metrics)

workflow.set_entry_point("start_job")
workflow.add_edge("start_job", "triage_document")
workflow.add_edge("triage_document", "extract_features")
workflow.add_edge("extract_features", "cre_and_route")
workflow.add_edge("cre_and_route", "map_summarize")
workflow.add_edge("map_summarize", "validate_map")

workflow.add_conditional_edges(
    "validate_map",
    should_escalate,
    {
        "escalate": "escalate_once",
        "compile": "reduce_compile",
        "compile_warn": "mark_warning",
    },
)

workflow.add_edge("escalate_once", "reduce_compile")
workflow.add_edge("mark_warning", "reduce_compile")
workflow.add_edge("reduce_compile", "store_for_rag")
workflow.add_edge("store_for_rag", "finalize_metrics")
workflow.add_edge("finalize_metrics", END)

agentic_graph = workflow.compile()

log.info("Capability-Routed Agentic Graph compiled successfully.")
