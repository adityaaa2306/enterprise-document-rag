"""
Agentic Orchestrator — Adaptive hierarchical carbon-aware pipeline.

Upload → Triage → Adaptive Chunking → Features → CRE → Map → QVA →
Plan/Freeze compile DAG → Immutable Regional/Chapter/Executive →
Summary Ready → (Background: embed/Chroma/BM25/carbon/telemetry)
"""
from __future__ import annotations

import logging
import concurrent.futures
import math
import time
from typing import TypedDict, List, Dict, Any, Optional

from langgraph.graph import StateGraph, END

from src.agents import triage, models, feature_extraction, quality_validation
from src.agents import chunk_features as chunk_features_mod
from src.agents import summarization_agents
from src.memory import storage
from src.memory.document_ids import align_chunks_to_document_id
from src.chunking import ChunkingService
from src.core import scheduler, cre, intelligent_router, chunk_router, hierarchy
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

_TIER_ORDER = ["light", "medium", "heavy"]


def _next_tier(tier: str) -> Optional[str]:
    t = (tier or "medium").lower()
    if t == "large":
        t = "heavy"
    try:
        i = _TIER_ORDER.index(t)
    except ValueError:
        return "heavy"
    if i >= len(_TIER_ORDER) - 1:
        return None
    return _TIER_ORDER[i + 1]


def _models_for_tier(tier: str, decision: Dict[str, Any]) -> List[str]:
    if tier == (decision.get("tier") or "") and decision.get("fallbacks"):
        return list(decision["fallbacks"])
    if tier == "light":
        return list(settings.light_models())
    if tier == "heavy":
        return list(settings.heavy_models())
    return list(settings.medium_models())


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
    # Adaptive pipeline
    chunk_features: List[Dict[str, Any]]
    chunk_routing: List[Dict[str, Any]]
    routing_distribution: Dict[str, Any]
    hierarchy: Dict[str, Any]
    agent_telemetry: List[Dict[str, Any]]
    carbon_budget_g: float
    carbon_spent_g: float
    carbon_remaining_g: float
    predicted_final_carbon_g: float
    map_checkpoint: Dict[str, Any]
    compile_meta: Dict[str, Any]
    # Unified pipeline DAG nodes (chunk + hierarchy) — dict id → node dict
    pipeline_dag_nodes: Dict[str, Any]
    # Pipeline intelligence (capability + strategy + explainability)
    pipeline_intelligence: Dict[str, Any]
    # Diagnostic only — stage + per-chunk timings
    ingestion_latency: Dict[str, Any]
    # Indices re-summarized in the last escalate step (incremental QVA)
    last_escalated_indices: List[int]


def _restore_pipeline_nodes(state: AgentState):
    """Rehydrate DagNode objects from state dicts produced by map_summarize."""
    raw = state.get("pipeline_dag_nodes") or {}
    if not raw:
        return None
    try:
        from src.core.pipeline_dag import DagNode

        out = {}
        for nid, d in raw.items():
            if isinstance(d, DagNode):
                out[nid] = d
                continue
            if not isinstance(d, dict):
                continue
            out[nid] = DagNode(
                id=str(d.get("id") or nid),
                kind=str(d.get("kind") or "chunk"),
                depth=int(d.get("depth") or 0),
                dep_ids=list(d.get("dep_ids") or []),
                parent_ids=list(d.get("parent_ids") or []),
                children_ids=list(d.get("children_ids") or []),
                status=str(d.get("status") or "pending"),
                assigned_model=d.get("assigned_model"),
                endpoint_id=d.get("endpoint_id"),
                worker_id=d.get("worker_id"),
                carbon_estimate_g=float(d.get("carbon_estimate_g") or 0.0),
                energy_kwh=float(d.get("energy_kwh") or 0.0),
                latency_ms=float(d.get("latency_ms") or 0.0),
                tokens_in=int(d.get("tokens_in") or 0),
                tokens_out=int(d.get("tokens_out") or 0),
                cost_usd=float(d.get("cost_usd") or 0.0),
                retries=int(d.get("retries") or 0),
                input_text=str(d.get("input_text") or ""),
                output_summary=str(d.get("output_summary") or ""),
                section_path=str(d.get("section_path") or ""),
                token_estimate=int(d.get("token_estimate") or 0),
                qva_confidence=float(d.get("qva_confidence") or 0.0),
                used_heavy=bool(d.get("used_heavy")),
                tier=d.get("tier"),
                chunk_index=d.get("chunk_index"),
            )
        return out or None
    except Exception as e:
        log.debug("restore pipeline nodes failed: %s", e)
        return None


def _set_progress(
    job_id: str,
    progress: float,
    message: str,
    *,
    force: bool = False,
) -> None:
    """Throttled DB progress writes; milestones use force=True."""
    try:
        from src.perf.progress import set_progress_throttled

        set_progress_throttled(job_id, progress, message, force=force)
    except Exception:
        job_store.set_progress(job_id, progress, message)


def _get_latency(state: AgentState) -> IngestionLatencyTracker:
    """Rebuild tracker from state dict (LangGraph may not preserve the object)."""
    raw = state.get("ingestion_latency")
    if isinstance(raw, IngestionLatencyTracker):
        return raw
    lat = IngestionLatencyTracker(job_id=state.get("job_id") or "")
    if isinstance(raw, dict):
        lat.stages.update(raw.get("stages_ms") or {})
        lat.stage_detail.update(raw.get("stage_detail") or {})
        lat.meta.update(raw.get("meta") or {})
        lat.chunk_calls = list(raw.get("chunk_calls") or [])
        lat.pool_samples = list(raw.get("pool_samples") or [])
        lat._peak_active = int(raw.get("pool_peak_active") or 0)
        lat._model_calls = int(raw.get("_model_calls") or 0)
        # Restore monotonic origin from elapsed_so_far so total_ms stays correct
        elapsed = raw.get("_elapsed_so_far_ms")
        if elapsed is not None:
            lat._t0 = time.perf_counter() - (float(elapsed) / 1000.0)
        cpu0 = raw.get("_cpu0")
        if cpu0 is not None:
            # Keep relative CPU accounting approximate across node rebuilds
            lat._cpu0 = float(cpu0)
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
    # Prefetch Electricity Maps (TTL-cached) so FEA/routing never block on HTTP.
    try:
        from src.perf.prefetch import start_grid_intensity_prefetch

        start_grid_intensity_prefetch()
    except Exception as e:
        log.debug("grid intensity prefetch skip: %s", e)
    return state


def triage_document(state: AgentState) -> Dict[str, Any]:
    job_id = state["job_id"]
    document_id = state.get("document_id") or job_id
    log.info(f"Job {job_id}: [2] Triaging document...")
    _set_progress(job_id, 12.0, "Triage: analyzing document layout...", force=True)
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
            _set_progress(job_id, 13.0, "Adaptive chunking...", force=True)
            embed_fn = None
            # Optional NIM similarity; fall back to lexical inside ChunkingService
            if models.get_nim_client() is not None:
                try:
                    embed_fn = models.embed_texts
                except Exception:
                    embed_fn = None
            forensics = None
            try:
                from src.monitoring.chunking_forensics import (
                    ChunkingForensics,
                    default_forensics_path,
                    forensics_enabled_from_env,
                )

                if forensics_enabled_from_env():
                    forensics = ChunkingForensics(enabled=True, job_id=job_id)
                    forensics.raw_block_count = len(raw_chunks)
                    from collections import Counter

                    forensics.element_counts = Counter(
                        str(getattr(c, "type", "Other")) for c in raw_chunks
                    )
            except Exception as fe:
                log.warning("Job %s: forensics init skipped: %s", job_id, fe)
                forensics = None

            if bool(getattr(settings, "USE_STRUCTURE_PARSER", True)):
                from src.structure.pipeline import DocumentStructurePipeline

                _set_progress(
                    job_id, 14.0, "Parsing document structure...", force=True
                )
                chunks, parents, meta = DocumentStructurePipeline(
                    embed_fn=embed_fn
                ).run(raw_chunks, document_id=document_id)
            else:
                chunks, parents, meta = ChunkingService(
                    embed_fn=embed_fn, forensics=forensics
                ).build(raw_chunks, document_id=document_id)
            if forensics is not None:
                try:
                    # Mirror structure diagnostics into forensics blob when present
                    sd = (meta or {}).get("structure_diagnostics") or {}
                    if sd:
                        forensics.extras["structure_diagnostics"] = sd
                        forensics.packed_chunk_count = int(
                            meta.get("chunk_count") or len(chunks)
                        )
                        forensics.semantic_group_count = int(
                            meta.get("semantic_sections") or 0
                        )
                        forensics.section_count = int(meta.get("section_count") or 0)
                    path = forensics.save(default_forensics_path(job_id))
                    log.info("Job %s: chunking forensics written to %s", job_id, path)
                    meta = dict(meta)
                    meta["forensics_path"] = path
                except Exception as fe:
                    log.warning("Job %s: forensics save failed: %s", job_id, fe)
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
    # Start embedding as soon as immutable chunk text exists (overlaps FEA/CRE/map).
    if bool(getattr(settings, "ENABLE_EMBED_PREFETCH", True)):
        try:
            from src.perf.prefetch import start_embed_prefetch

            start_embed_prefetch(job_id, chunks)
        except Exception as e:
            log.debug("early embed prefetch skip: %s", e)
    return {
        "chunks": chunks,
        "total_chunks": len(chunks),
        "triage_meta": triage_meta,
        "chunk_parents": chunk_parents,
        "ingestion_latency": _persist_latency(lat),
    }


def extract_features_node(state: AgentState) -> Dict[str, Any]:
    job_id = state["job_id"]
    log.info(f"Job {job_id}: [3] Feature Extraction (document + per-chunk)...")
    _set_progress(job_id, 20.0, "Extracting capability features...")
    lat = _get_latency(state)

    triage_meta = state.get("triage_meta") or {"strategy": settings.TRIAGE_STRATEGY}
    per_chunk: List[Dict[str, Any]] = []
    with lat.stage(STAGE_FEATURE_EXTRACT):
        try:
            features = feature_extraction.extract_features(state["chunks"], triage_meta)
            log.info(
                "Job %s: feature extraction complete via %s",
                job_id,
                (features or {}).get("classifier_method"),
            )
        except Exception as e:
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
        try:
            per_chunk = chunk_features_mod.extract_chunk_features(state["chunks"])
            chunk_features_mod.attach_features_to_chunks(state["chunks"], per_chunk)
        except Exception as e:
            log.warning("Job %s: chunk feature extraction failed: %s", job_id, e)
            per_chunk = []
    lat.add_meta(
        feature_classifier=(features or {}).get("classifier_method"),
        document_type=(features or {}).get("document_type"),
        chunk_feature_count=len(per_chunk),
    )
    return {
        "features": features,
        "chunk_features": per_chunk,
        "ingestion_latency": _persist_latency(lat),
    }


def plan_pipeline(state: AgentState) -> Dict[str, Any]:
    """Document capability analysis + adaptive strategy selection (pre-map)."""
    job_id = state["job_id"]
    if not bool(getattr(settings, "PIPELINE_INTELLIGENCE_ENABLED", True)):
        return {}
    log.info("Job %s: [3b] Pipeline intelligence — capability + strategy", job_id)
    _set_progress(job_id, 24.0, "Analyzing document capability & selecting strategy...")
    lat = _get_latency(state)
    from src.core.pipeline_intelligence import plan_pipeline_intelligence

    intensity = float((state.get("features") or {}).get("grid_intensity") or 0) or float(
        getattr(settings, "LOCAL_GRID_INTENSITY", 700) or 700
    )
    with lat.stage("plan_pipeline_ms"):
        intel = plan_pipeline_intelligence(
            chunks=list(state.get("chunks") or []),
            features=dict(state.get("features") or {}),
            chunk_features=list(state.get("chunk_features") or []),
            triage_meta=state.get("triage_meta"),
            chunk_parents=state.get("chunk_parents"),
            job_mode=state.get("job_mode") or "automatic",
            carbon_intensity=intensity,
        )
    strat = (intel or {}).get("strategy") or {}
    lat.add_meta(
        strategy_id=strat.get("strategy_id"),
        document_scale=(intel.get("capability_profile") or {}).get("document_scale"),
        map_mode=strat.get("map_mode"),
        compile_depth=strat.get("compile_depth_label"),
    )
    log.info(
        "Job %s: strategy=%s scale=%s map_mode=%s compile=%s",
        job_id,
        strat.get("strategy_id"),
        (intel.get("capability_profile") or {}).get("document_scale"),
        strat.get("map_mode"),
        strat.get("compile_depth_label"),
    )
    return {
        "pipeline_intelligence": intel,
        "ingestion_latency": _persist_latency(lat),
    }


def cre_and_route(state: AgentState) -> Dict[str, Any]:
    job_id = state["job_id"]
    mode = (state.get("job_mode") or "automatic").lower()
    log.info(f"Job {job_id}: [4] CRE + Adaptive chunk router (preference={mode})...")
    _set_progress(job_id, 28.0, "Computing capability requirement & routing...")
    lat = _get_latency(state)

    budget_g = float(getattr(settings, "CARBON_BUDGET_G", 40.0) or 40.0)
    budget_enabled = bool(getattr(settings, "CARBON_BUDGET_ENABLED", True))
    intel = state.get("pipeline_intelligence") or {}
    strategy = dict(intel.get("strategy") or {})
    if strategy.get("carbon_budget_g"):
        budget_g = float(strategy["carbon_budget_g"])
    intensity = float((state.get("features") or {}).get("grid_intensity") or 0) or float(
        getattr(settings, "LOCAL_GRID_INTENSITY", 700) or 700
    )

    with lat.stage(STAGE_CRE_ROUTE):
        cre_result = cre.compute_crs(state["features"])
        decision = intelligent_router.route(cre_result, state["features"], mode=mode)

        chunk_feats = list(state.get("chunk_features") or [])
        if not chunk_feats and state.get("chunks"):
            chunk_feats = chunk_features_mod.extract_chunk_features(state["chunks"])

        if bool(getattr(settings, "ADAPTIVE_CHUNK_ROUTING", True)) and chunk_feats:
            chunk_decisions = chunk_router.route_chunks(
                chunk_feats,
                cre_result=cre_result.to_dict(),
                routing_decision=decision.to_dict(),
                carbon_remaining_g=budget_g if budget_enabled else None,
                budget_enabled=budget_enabled,
                strategy=strategy,
                carbon_intensity=intensity,
            )
        else:
            chunk_decisions = [
                chunk_router.ChunkRouteDecision(
                    chunk_index=i,
                    tier=decision.tier,
                    model=decision.selected_model,
                    reason=f"Job-level tier={decision.tier}",
                    expected_quality=0.95,
                    expected_carbon_g=0.18,
                    expected_latency_ms=1600,
                )
                for i in range(len(state.get("chunks") or []))
            ]
        dist = chunk_router.routing_distribution(chunk_decisions)
        predicted = float(dist.get("predicted_carbon_g") or 0.0)

        # Enrich intelligence report with routing mix
        if intel:
            from src.core.pipeline_intelligence import enrich_report_after_run

            intel = enrich_report_after_run(
                intel,
                routing_distribution=dist,
                cre_result=cre_result.to_dict(),
            )

    routing_summary = (
        f"tier={decision.tier} model={decision.selected_model} "
        f"crs={cre_result.crs:.3f} min_tier={cre_result.min_tier} "
        f"compile={decision.compile_tier} reason={decision.reason_summary} "
        f"routes=L{dist.get('light',0)}/M{dist.get('medium',0)}/H{dist.get('heavy',0)}"
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
        routing_distribution=dist,
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
        "chunk_features": chunk_feats,
        "chunk_routing": [d.to_dict() for d in chunk_decisions],
        "routing_distribution": dist,
        "carbon_budget_g": budget_g,
        "carbon_spent_g": 0.0,
        "carbon_remaining_g": budget_g,
        "predicted_final_carbon_g": predicted,
        "pipeline_intelligence": intel or state.get("pipeline_intelligence"),
        "ingestion_latency": _persist_latency(lat),
    }


def map_summarize_routed(state: AgentState) -> Dict[str, Any]:
    job_id = state["job_id"]
    decision = state["routing_decision"]
    default_tier = decision["tier"]
    default_chain = decision.get("fallbacks") or [decision["selected_model"]]
    lat = _get_latency(state)
    routes = {
        int(r.get("chunk_index", i)): r
        for i, r in enumerate(state.get("chunk_routing") or [])
    }

    log.info("Job %s: [5] Adaptive map summarize (capacity-aware scheduler)", job_id)
    _set_progress(job_id, 35.0, "Summarizing chunks with adaptive routing...", force=True)

    chunks = state["chunks"]
    total = state["total_chunks"]
    summaries: List[str] = [""] * len(chunks)
    agent_telemetry: List[Dict[str, Any]] = list(state.get("agent_telemetry") or [])
    checkpoint = dict(state.get("map_checkpoint") or {})
    done_set = set(int(x) for x in (checkpoint.get("completed_indices") or []))
    max_workers = max(1, int(settings.effective_map_max_workers()))
    intensity = float((state.get("features") or {}).get("grid_intensity") or 500.0)
    # Task 1: real pending chunk nodes in the unified pipeline DAG
    pipeline_nodes = _restore_pipeline_nodes(state) or {}
    try:
        from src.core import pipeline_dag as pdag

        if not pipeline_nodes:
            pipeline_nodes = pdag.build_chunk_nodes(chunks, routes=routes)
    except Exception as e:
        log.debug("pipeline chunk nodes skip: %s", e)
        pipeline_nodes = {}
    lat.add_meta(
        map_max_workers=max_workers,
        adaptive_chunk_routing=True,
        capacity_scheduler=bool(getattr(settings, "CAPACITY_SCHEDULER_ENABLED", True)),
        embedded_worker=bool(getattr(settings, "RUN_EMBEDDED_WORKER", False)),
        unified_dag_chunks=len(pipeline_nodes),
    )
    stage_t0 = time.perf_counter()
    carbon_spent = float(state.get("carbon_spent_g") or 0.0)

    if bool(getattr(settings, "ENABLE_EMBED_PREFETCH", True)):
        try:
            from src.perf.prefetch import start_embed_prefetch

            start_embed_prefetch(job_id, chunks)
        except Exception as e:
            log.debug("embed prefetch skip: %s", e)

    def _run(idx_chunk, deadline_mono: Optional[float] = None):
        idx, chunk = idx_chunk
        route = routes.get(idx) or {}
        tier = str(route.get("tier") or default_tier)
        chain = _models_for_tier(tier, decision) or default_chain
        lat.worker_enter()
        try:
            # Hard isolation: HTTP client timeout is below MAP wall; wrap again
            # so a stuck socket cannot block the capacity worker forever.
            from src.core.pipeline_executor import _run_with_hard_isolation

            hard_iso = float(
                getattr(settings, "MAP_CHUNK_HARD_TIMEOUT_SEC", 90.0) or 90.0
            )

            def _invoke():
                return summarization_agents.run_summarization_agent(
                    chunk.content,
                    state,
                    tier=tier,
                    model_ids=chain,
                    grid_intensity=intensity,
                    deadline_mono=deadline_mono,
                    task_id=f"chunk-{idx}",
                )

            result = _run_with_hard_isolation(
                _invoke, hard_timeout_sec=hard_iso, label=f"chunk-{idx}"
            )
            # Update unified DAG chunk node
            nid = f"chunk-{idx}"
            if nid in pipeline_nodes:
                node = pipeline_nodes[nid]
                node.status = "completed" if result.success and (result.summary or "").strip() else "failed"
                node.output_summary = (result.summary or "").strip()
                node.assigned_model = result.model_id
                node.tier = tier
                node.latency_ms = float(result.latency_ms or 0.0)
                node.carbon_estimate_g = float(result.carbon_estimate_g or 0.0)
                node.tokens_in = int(result.input_tokens or 0)
                node.tokens_out = int(result.output_tokens or 0)
                try:
                    from src.core.node_accounting import estimate_node_accounting

                    acct = estimate_node_accounting(
                        tier=tier,
                        tokens_in=node.tokens_in,
                        tokens_out=node.tokens_out,
                        latency_ms=node.latency_ms,
                        grid_intensity=intensity,
                        model_id=result.model_id,
                    )
                    node.energy_kwh = float(acct["energy_kwh"])
                    node.cost_usd = float(acct["cost_usd"])
                    node.carbon_estimate_g = float(acct["carbon_g"])
                except Exception:
                    pass
                node.finished_at = time.monotonic()
            lat.record_chunk_call(
                {
                    "chunk_index": idx,
                    "tier": tier,
                    "model_id": result.model_id or (chain[0] if chain else None),
                    "queue_ms": 0.0,
                    "call_ms": round(result.latency_ms, 1),
                    "success": result.success,
                    "retry_count": 0,
                    "attempt_count": 1,
                    "http_status": None,
                    "attempts": [],
                    "phase": "map",
                    "route_reason": route.get("reason"),
                    "carbon_estimate_g": result.carbon_estimate_g,
                }
            )
            return idx, result
        finally:
            lat.worker_exit()

    with lat.stage(STAGE_MAP_SUMMARIZE):
        pending = [(i, c) for i, c in enumerate(chunks) if i not in done_set]
        prev = checkpoint.get("summaries") or []
        for i in done_set:
            if 0 <= i < len(summaries) and i < len(prev):
                summaries[i] = prev[i]

        use_sched = bool(getattr(settings, "CAPACITY_SCHEDULER_ENABLED", True))
        hard_to = float(
            getattr(settings, "MAP_CHUNK_HARD_TIMEOUT_SEC", 90.0) or 90.0
        )
        empty_attempts = max(
            1, int(getattr(settings, "MAP_EMPTY_RETRY_ATTEMPTS", 2) or 2)
        )

        def _is_ok(res) -> bool:
            if res is None:
                return False
            try:
                _idx, result = res
            except Exception:
                return False
            text = (getattr(result, "summary", None) or "").strip()
            return bool(text) and bool(getattr(result, "success", True))

        def _on_progress(prog, mets) -> None:
            done = prog.completed + len(done_set)
            pct = 35.0 + (done / max(total, 1)) * 25.0
            _set_progress(job_id, pct, prog.message("Summarizing"), force=False)
            try:
                from src.core.execution_scheduler import map_progress_partial
                from src.core import pipeline_dag as pdag

                job_store.JOB_STATUSES.setdefault(job_id, {})
                partial = map_progress_partial(prog, mets)
                partial["chunks_done"] = prog.completed
                partial["chunks_total"] = total
                # Mark running chunk nodes
                busy = int(prog.running or 0)
                if pipeline_nodes:
                    for nid, node in pipeline_nodes.items():
                        if node.status == "pending" and node.chunk_index is not None:
                            # leave pending until completed in _run
                            pass
                    snap = pdag.dag_progress_snapshot(
                        pipeline_nodes,
                        workers_busy=busy,
                        workers_total=max_workers,
                    )
                    elapsed = time.perf_counter() - stage_t0
                    rate = prog.completed / elapsed if elapsed > 0.5 and prog.completed else 0.0
                    rem = max(0, total - prog.completed - len(done_set))
                    eta = (rem / rate) if rate > 0 else None
                    snap["eta_sec"] = round(eta, 1) if eta is not None else None
                    snap["carbon_g"] = round(
                        sum(float(n.carbon_estimate_g or 0) for n in pipeline_nodes.values()),
                        4,
                    )
                    partial["dag"] = snap
                    partial["workers_busy"] = busy
                    partial["workers_total"] = max_workers
                    partial["avg_latency_ms"] = snap.get("avg_latency_ms")
                    partial["carbon_g"] = snap.get("carbon_g")
                    partial["remaining_tasks"] = rem
                    partial["eta_sec"] = snap.get("eta_sec")
                job_store.JOB_STATUSES[job_id]["partial"] = partial
            except Exception:
                pass

        if use_sched and pending:
            from src.core.execution_scheduler import run_capacity_pool

            ordered, prog, mets = run_capacity_pool(
                pending,
                _run,
                role="map",
                kind="map",
                max_workers=max_workers,
                hard_timeout_sec=hard_to,
                max_attempts=empty_attempts,
                is_success=_is_ok,
                on_progress=_on_progress,
            )
            for idx, _chunk in pending:
                res = ordered[idx] if idx < len(ordered) else None
                if res is None:
                    summaries[idx] = ""
                    agent_telemetry.append(
                        {
                            "chunk_index": idx,
                            "phase": "map",
                            "success": False,
                            "error": "scheduler_failed_or_empty",
                        }
                    )
                    done_set.add(idx)
                    continue
                _idx, result = res
                summaries[idx] = (result.summary or "").strip()
                agent_telemetry.append(
                    result.to_dict() | {"chunk_index": idx, "phase": "map"}
                )
                carbon_spent += float(result.carbon_estimate_g or 0.0)
                done_set.add(idx)
            lat.add_meta(scheduler=mets.to_dict(), map_progress=prog.snapshot())
            _on_progress(prog, mets)
        else:
            # Legacy submit path (feature flag off) — capacity-capped + non-blocking exit
            submit_times: Dict[int, float] = {}
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
            future_to_idx = {}
            try:
                for i, c in pending:
                    submit_times[i] = time.perf_counter()
                    future_to_idx[executor.submit(_run, (i, c))] = i
                for fut in concurrent.futures.as_completed(future_to_idx):
                    idx = future_to_idx[fut]
                    try:
                        idx, result = fut.result(timeout=hard_to)
                        summaries[idx] = (result.summary or "").strip()
                        agent_telemetry.append(
                            result.to_dict() | {"chunk_index": idx, "phase": "map"}
                        )
                        carbon_spent += float(result.carbon_estimate_g or 0.0)
                    except Exception as e:
                        log.error("Job %s: map chunk %s failed: %s", job_id, idx, e)
                        summaries[idx] = ""
                        agent_telemetry.append(
                            {
                                "chunk_index": idx,
                                "phase": "map",
                                "success": False,
                                "error": str(e)[:300],
                            }
                        )
                    done_set.add(idx)
                    done = len(done_set)
                    _set_progress(
                        job_id,
                        35.0 + (done / max(total, 1)) * 25.0,
                        f"Summarizing... completed {done}/{total}",
                    )
            finally:
                # Never join hung NIM threads on map exit
                try:
                    models._shutdown_executor_nowait(executor)
                except Exception:
                    try:
                        executor.shutdown(wait=False, cancel_futures=True)
                    except TypeError:
                        executor.shutdown(wait=False)

    budget = float(state.get("carbon_budget_g") or settings.CARBON_BUDGET_G)
    lat.add_meta(map_wall_ms=round((time.perf_counter() - stage_t0) * 1000.0, 1))
    # Serialize DAG nodes for state (dataclasses → dicts)
    dag_nodes_ser = {}
    for nid, n in pipeline_nodes.items():
        try:
            dag_nodes_ser[nid] = n.to_dict() if hasattr(n, "to_dict") else n
        except Exception:
            pass
    return {
        "summaries": summaries,
        "agent_telemetry": agent_telemetry,
        "carbon_spent_g": round(carbon_spent, 4),
        "carbon_remaining_g": round(max(0.0, budget - carbon_spent), 4),
        "map_checkpoint": {
            "completed_indices": sorted(done_set),
            "summaries": summaries,
        },
        "pipeline_dag_nodes": dag_nodes_ser,
        "ingestion_latency": _persist_latency(lat),
    }


def validate_map(state: AgentState) -> Dict[str, Any]:
    job_id = state["job_id"]
    log.info(f"Job {job_id}: [6] Quality Validation (map)...")
    _set_progress(job_id, 65.0, "Validating summary quality...", force=True)
    lat = _get_latency(state)

    with lat.stage(STAGE_VALIDATE):
        strat = ((state.get("pipeline_intelligence") or {}).get("strategy") or {})
        tau = strat.get("qva_confidence_threshold")
        summaries = list(state.get("summaries") or [])
        # Never send empty summaries through QVA — mark failed and validate the rest.
        empty_idx = [
            i for i, s in enumerate(summaries) if not (s or "").strip()
        ]
        only_idx = list(state.get("last_escalated_indices") or [])
        if empty_idx:
            log.warning(
                "Job %s: %s empty summaries skipped for QVA (failed without evaluate)",
                job_id,
                len(empty_idx),
            )
        prior_raw = ((state.get("validation_verdict") or {}).get("details") or {}).get(
            "chunk_verdicts"
        )
        prior_verdicts = None
        if only_idx and prior_raw and len(prior_raw) == len(summaries):
            prior_verdicts = []
            for d in prior_raw:
                if not isinstance(d, dict):
                    prior_verdicts.append(None)
                    continue
                prior_verdicts.append(
                    quality_validation.ValidationVerdict(
                        passed=bool(d.get("passed")),
                        confidence=float(d.get("confidence") or 0),
                        faithfulness=float(d.get("faithfulness") or 0),
                        coverage=float(d.get("coverage") or 0),
                        hallucination_rate=float(d.get("hallucination_rate") or 0),
                        contradiction_rate=float(d.get("contradiction_rate") or 0),
                        codes=list(d.get("codes") or []),
                        details=dict(d.get("details") or {}),
                        semantic_similarity=float(d.get("semantic_similarity") or 0),
                        entity_retention=float(d.get("entity_retention") or 0),
                        compression_ratio=float(d.get("compression_ratio") or 0),
                        redundancy=float(d.get("redundancy") or 0),
                        readability=float(d.get("readability") or 0),
                    )
                )
            # Incremental: only re-check non-empty escalated indices
            check_idx = [i for i in only_idx if i not in empty_idx]
            if check_idx:
                verdict = quality_validation.validate_chunks(
                    state["chunks"],
                    summaries,
                    confidence_threshold=float(tau) if tau is not None else None,
                    only_indices=check_idx,
                    prior_verdicts=prior_verdicts,
                )
            else:
                verdict = quality_validation.validate_chunks(
                    state["chunks"],
                    summaries,
                    confidence_threshold=float(tau) if tau is not None else None,
                    only_indices=[],
                    prior_verdicts=prior_verdicts,
                )
        else:
            non_empty = [i for i in range(len(summaries)) if i not in empty_idx]
            if non_empty and empty_idx:
                # Validate non-empty only; inject empty failures after.
                placeholder = [
                    s if (s or "").strip() else " "
                    for s in summaries
                ]
                verdict = quality_validation.validate_chunks(
                    state["chunks"],
                    placeholder,
                    confidence_threshold=float(tau) if tau is not None else None,
                    only_indices=non_empty,
                    prior_verdicts=[None] * len(summaries),
                )
            elif non_empty:
                verdict = quality_validation.validate_chunks(
                    state["chunks"],
                    summaries,
                    confidence_threshold=float(tau) if tau is not None else None,
                )
            else:
                verdict = quality_validation.ValidationVerdict(
                    passed=False,
                    confidence=0.0,
                    faithfulness=0.0,
                    coverage=0.0,
                    hallucination_rate=1.0,
                    contradiction_rate=0.0,
                    codes=["all_summaries_empty"],
                    details={
                        "failed_indices": list(empty_idx),
                        "chunk_fail_ratio_high": True,
                    },
                )
        if empty_idx and hasattr(verdict, "details"):
            details = dict(verdict.details or {})
            failed = list(details.get("failed_indices") or [])
            for i in empty_idx:
                if i not in failed:
                    failed.append(i)
            details["failed_indices"] = sorted(failed)
            details["empty_summary_indices"] = list(empty_idx)
            codes = list(verdict.codes or [])
            if "empty_summary" not in codes:
                codes.append("empty_summary")
            verdict = quality_validation.ValidationVerdict(
                passed=False,
                confidence=float(verdict.confidence or 0),
                faithfulness=float(verdict.faithfulness or 0),
                coverage=float(verdict.coverage or 0),
                hallucination_rate=float(verdict.hallucination_rate or 0),
                contradiction_rate=float(verdict.contradiction_rate or 0),
                codes=codes,
                details=details,
                semantic_similarity=float(getattr(verdict, "semantic_similarity", 0) or 0),
                entity_retention=float(getattr(verdict, "entity_retention", 0) or 0),
                compression_ratio=float(getattr(verdict, "compression_ratio", 0) or 0),
                redundancy=float(getattr(verdict, "redundancy", 0) or 0),
                readability=float(getattr(verdict, "readability", 0) or 0),
            )
    log.info(
        f"Job {job_id}: QVA map passed={verdict.passed} conf={verdict.confidence} "
        f"codes={verdict.codes}"
    )
    return {
        "validation_verdict": verdict.to_dict(),
        "last_escalated_indices": [],
        "ingestion_latency": _persist_latency(lat),
    }


def should_escalate(state: AgentState) -> str:
    verdict = state.get("validation_verdict") or {}
    esc = int(state.get("escalation_count") or 0)
    strat = ((state.get("pipeline_intelligence") or {}).get("strategy") or {})
    max_esc = int(
        strat.get("max_escalations")
        if strat.get("max_escalations") is not None
        else settings.QVA_MAX_ESCALATIONS
    )

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
    """Escalate ONLY failed chunks one tier (Light→Medium→Heavy).

    Failed chunks are dispatched concurrently via the capacity-aware pull
    scheduler (never a sequential loop, never submit-all past endpoint capacity).
    """
    job_id = state["job_id"]
    verdict = state.get("validation_verdict") or {}
    codes = verdict.get("codes") or ["validation_failed"]
    lat = _get_latency(state)

    raw = dict(state["routing_decision"])
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

    confidences = details.get("chunk_confidences") or []
    if confidences and len(confidences) == len(state.get("summaries") or []):
        failed_idx = sorted(
            failed_idx,
            key=lambda i: confidences[i] if 0 <= i < len(confidences) else 0.0,
        )
    max_esc_chunks = max(
        1,
        int(
            (
                ((state.get("pipeline_intelligence") or {}).get("strategy") or {}).get(
                    "max_escalate_chunks"
                )
            )
            or getattr(settings, "QVA_MAX_ESCALATE_CHUNKS", 8)
            or 8
        ),
    )
    if len(failed_idx) > max_esc_chunks:
        failed_idx = failed_idx[:max_esc_chunks]

    routes = {
        int(r.get("chunk_index", i)): dict(r)
        for i, r in enumerate(state.get("chunk_routing") or [])
    }
    summaries = list(state["summaries"])
    agent_telemetry = list(state.get("agent_telemetry") or [])
    carbon_spent = float(state.get("carbon_spent_g") or 0.0)
    intensity = float((state.get("features") or {}).get("grid_intensity") or 500.0)
    max_workers = max(1, int(settings.effective_map_max_workers()))

    log.info(
        "Job %s: [6b] Escalating %s failed chunks (capacity scheduler, workers=%s, step %s)",
        job_id,
        len(failed_idx),
        max_workers,
        esc_count,
    )
    _set_progress(
        job_id,
        70.0,
        f"Escalating failed chunks ({len(failed_idx)}) step {esc_count}...",
        force=True,
    )

    def _run(idx, deadline_mono: Optional[float] = None):
        route = routes.get(idx) or {}
        cur = str(route.get("tier") or decision.tier)
        nxt = _next_tier(cur) or "heavy"
        chain = _models_for_tier(nxt, decision.to_dict())
        lat.worker_enter()
        try:
            from src.core.pipeline_executor import _run_with_hard_isolation

            hard_iso = float(
                getattr(settings, "MAP_CHUNK_HARD_TIMEOUT_SEC", 90.0) or 90.0
            )

            def _invoke():
                return summarization_agents.run_summarization_agent(
                    state["chunks"][idx].content,
                    state,
                    tier=nxt,
                    model_ids=chain,
                    grid_intensity=intensity,
                    deadline_mono=deadline_mono,
                    task_id=f"chunk-{idx}",
                )

            result = _run_with_hard_isolation(
                _invoke, hard_timeout_sec=hard_iso, label=f"esc-chunk-{idx}"
            )
            lat.record_chunk_call(
                {
                    "chunk_index": idx,
                    "tier": nxt,
                    "model_id": result.model_id,
                    "queue_ms": 0.0,
                    "call_ms": round(result.latency_ms, 1),
                    "success": result.success,
                    "retry_count": 0,
                    "attempt_count": 1,
                    "phase": "escalate",
                    "from_tier": cur,
                }
            )
            return idx, nxt, result
        finally:
            lat.worker_exit()

    with lat.stage(STAGE_ESCALATE):
        hard_to = float(getattr(settings, "MAP_CHUNK_HARD_TIMEOUT_SEC", 90.0) or 90.0)
        use_sched = bool(getattr(settings, "CAPACITY_SCHEDULER_ENABLED", True))

        def _is_ok(res) -> bool:
            if res is None:
                return False
            try:
                _i, _n, result = res
            except Exception:
                return False
            return bool((getattr(result, "summary", None) or "").strip())

        if use_sched and failed_idx:
            from src.core.execution_scheduler import run_capacity_pool

            # Payloads as (idx,) tuples so ordered results key by index
            payloads = [(i,) for i in failed_idx]

            def _run_wrapped(payload, deadline_mono: Optional[float] = None):
                return _run(payload[0], deadline_mono=deadline_mono)

            ordered, prog, mets = run_capacity_pool(
                payloads,
                _run_wrapped,
                role="map",
                kind="repair",
                max_workers=max_workers,
                hard_timeout_sec=hard_to,
                max_attempts=max(1, int(getattr(settings, "MAP_EMPTY_RETRY_ATTEMPTS", 2) or 2)),
                is_success=_is_ok,
                on_progress=lambda p, m: _set_progress(
                    job_id,
                    70.0 + 10.0 * (p.completed / max(len(failed_idx), 1)),
                    p.message("Escalating"),
                ),
            )
            for i in failed_idx:
                res = ordered[i] if i < len(ordered) else None
                if res is None:
                    continue
                idx, nxt, result = res
                summaries[idx] = (result.summary or "").strip()
                agent_telemetry.append(
                    result.to_dict()
                    | {
                        "chunk_index": idx,
                        "phase": "escalate",
                        "escalation_step": esc_count,
                        "to_tier": nxt,
                    }
                )
                carbon_spent += float(result.carbon_estimate_g or 0.0)
                routes[idx] = {**(routes.get(idx) or {}), "tier": nxt}
            lat.add_meta(escalate_scheduler=mets.to_dict())
            done = prog.completed
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(_run, idx): idx for idx in failed_idx}
                done = 0
                for fut in concurrent.futures.as_completed(futures):
                    idx, nxt, result = fut.result()
                    summaries[idx] = (result.summary or "").strip()
                    agent_telemetry.append(
                        result.to_dict()
                        | {
                            "chunk_index": idx,
                            "phase": "escalate",
                            "escalation_step": esc_count,
                        }
                    )
                    carbon_spent += float(result.carbon_estimate_g or 0.0)
                    routes[idx] = {**(routes.get(idx) or {}), "tier": nxt}
                    done += 1
                    _set_progress(
                        job_id,
                        70.0 + 10.0 * (done / max(len(failed_idx), 1)),
                        f"Escalating... completed {done}/{len(failed_idx)}",
                    )

    # Validation runs once in validate_map (incremental for escalated indices).
    # Do NOT revalidate here — that duplicated full QVA every escalate cycle.
    budget = float(state.get("carbon_budget_g") or settings.CARBON_BUDGET_G)
    lat.add_meta(escalated_chunks=len(failed_idx), escalate_step=esc_count)
    return {
        "routing_decision": decision.to_dict(),
        "chunk_routing": list(routes.values())
        if routes
        else list(state.get("chunk_routing") or []),
        "summaries": summaries,
        "escalation_count": esc_count,
        "chunks_escalated": int(state.get("chunks_escalated") or 0) + len(failed_idx),
        "last_escalated_indices": list(failed_idx),
        "agent_telemetry": agent_telemetry,
        "carbon_spent_g": round(carbon_spent, 4),
        "carbon_remaining_g": round(max(0.0, budget - carbon_spent), 4),
        "ingestion_latency": _persist_latency(lat),
    }


def mark_warning(state: AgentState) -> Dict[str, Any]:
    return {"accept_with_warning": True}


def reduce_compile(state: AgentState) -> Dict[str, Any]:
    job_id = state["job_id"]
    decision = state["routing_decision"]
    lat = _get_latency(state)
    strat = ((state.get("pipeline_intelligence") or {}).get("strategy") or {})
    node_t0 = time.monotonic()
    reduce_max = float(getattr(settings, "REDUCE_COMPILE_MAX_SEC", 270.0) or 270.0)
    call_max = float(getattr(settings, "COMPILE_CALL_MAX_SEC", 180.0) or 180.0)
    budget = float(state.get("carbon_budget_g") or settings.CARBON_BUDGET_G)
    carbon_spent = float(state.get("carbon_spent_g") or 0.0)
    carbon_budget_on = bool(getattr(settings, "CARBON_BUDGET_ENABLED", True))

    compile_meta: Dict[str, Any] = {
        "medium_first": bool(strat.get("medium_first", True)),
        "used_heavy": False,
        "strategy_id": strat.get("strategy_id"),
        "compile_depth_label": strat.get("compile_depth_label"),
        "branch_recompiles": [],
        "compile_calls": 0,
        "compile_carbon_g": 0.0,
        "medium_compile_ms": None,
        "quality_check_ms": None,
        "heavy_compile_ms": None,
        "branch_repair_ms": None,
        "global_recompile_ms": None,
        "skipped_steps": [],
        "used_stitched_fallback": False,
        "reduce_compile_budget_sec": reduce_max,
    }

    log.info(
        "Job %s: [7] Adaptive hierarchical compile (node_budget=%.0fs call_budget=%.0fs)",
        job_id,
        reduce_max,
        call_max,
    )
    _set_progress(job_id, 82.0, "Building hierarchy & compiling summary...", force=True)

    def _node_remaining() -> float:
        return reduce_max - (time.monotonic() - node_t0)

    def _carbon_remaining() -> float:
        return max(0.0, budget - carbon_spent)

    def _estimate_compile_carbon_g(chain: List[str]) -> float:
        # Priors aligned with chunk_router tiers; compile prompts are heavier.
        heavy_ids = set(settings.heavy_models())
        if chain and any(m in heavy_ids for m in chain[:1]):
            return 0.41
        return 0.25

    def _can_start_expensive_repair(*, step: str, min_sec: float = 15.0) -> bool:
        """Gate heavy/repair/recompile on node time ceiling AND carbon remaining."""
        if _node_remaining() < min_sec:
            compile_meta["skipped_steps"].append(
                {"step": step, "reason": "reduce_compile_time_ceiling"}
            )
            log.warning(
                "Job %s: skipping %s — REDUCE_COMPILE_MAX_SEC remaining=%.1fs",
                job_id,
                step,
                _node_remaining(),
            )
            return False
        if carbon_budget_on and _carbon_remaining() <= 0.0:
            compile_meta["skipped_steps"].append(
                {"step": step, "reason": "carbon_budget_exhausted"}
            )
            log.warning(
                "Job %s: skipping %s — carbon budget exhausted (spent=%.3f budget=%.3f)",
                job_id,
                step,
                carbon_spent,
                budget,
            )
            return False
        return True

    def _compile_call(
        label: str,
        progress: float,
        inputs: List[str],
        chain: List[str],
        *,
        step_key: str,
    ) -> str:
        """Run a NIM compile with heartbeats; never block past the shared wall on join."""
        nonlocal carbon_spent
        _set_progress(job_id, progress, label)
        # Cap this call by both per-call wall and remaining node budget.
        max_wait = max(1.0, min(call_max, _node_remaining()))
        deadline_mono = time.monotonic() + max_wait
        started = time.monotonic()
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        fut = pool.submit(
            models.run_compile_with_models,
            inputs,
            state,
            chain,
            deadline_mono=deadline_mono,
        )
        try:
            while True:
                try:
                    result = fut.result(timeout=15.0)
                    elapsed_ms = (time.monotonic() - started) * 1000.0
                    carbon_g = _estimate_compile_carbon_g(chain)
                    carbon_spent += carbon_g
                    compile_meta["compile_calls"] = int(compile_meta["compile_calls"]) + 1
                    compile_meta["compile_carbon_g"] = round(
                        float(compile_meta["compile_carbon_g"]) + carbon_g, 4
                    )
                    compile_meta[step_key] = round(elapsed_ms, 1)
                    lat.record_chunk_call(
                        {
                            "chunk_index": -1,
                            "tier": "heavy" if "heavy" in label.lower() or step_key.startswith(
                                ("heavy", "branch", "global")
                            )
                            else "medium",
                            "model_id": (chain[0] if chain else None),
                            "queue_ms": 0.0,
                            "call_ms": round(elapsed_ms, 1),
                            "success": True,
                            "retry_count": 0,
                            "attempt_count": 1,
                            "phase": "compile",
                            "compile_step": step_key,
                            "carbon_estimate_g": carbon_g,
                        }
                    )
                    return result
                except concurrent.futures.TimeoutError:
                    elapsed = time.monotonic() - started
                    if elapsed >= max_wait:
                        log.error(
                            "Job %s: compile call timed out after %.0fs (%s)",
                            job_id,
                            elapsed,
                            label,
                        )
                        compile_meta[step_key] = round(elapsed * 1000.0, 1)
                        raise TimeoutError(
                            f"Compile step exceeded {max_wait:.0f}s while: {label}"
                        )
                    if job_store.is_cancel_requested(job_id):
                        raise RuntimeError("Compile cancelled by user")
                    _set_progress(
                        job_id,
                        progress,
                        f"{label} — waiting on model... ({int(elapsed)}s)",
                        force=True,
                    )
        finally:
            # Do not join a hung NIM thread — HTTP timeout must reclaim it.
            try:
                fut.cancel()
            except Exception:
                pass
            try:
                pool.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                pool.shutdown(wait=False)

    with lat.stage(STAGE_COMPILE):
        levels = []
        compile_inputs = list(state.get("summaries") or [])
        fan_in = max(
            2,
            int(
                strat.get("hierarchy_fan_in")
                or getattr(settings, "COMPILE_BATCH_SIZE", 8)
                or 8
            ),
        )
        max_depth = max(2, int(strat.get("hierarchy_max_depth") or 12))
        skip_regional = int(strat.get("skip_regional_below") or 0)
        if bool(getattr(settings, "ADAPTIVE_REGIONAL_HIERARCHY", True)):
            levels = hierarchy.build_hierarchy_levels(
                state.get("chunks") or [],
                state.get("summaries") or [],
                fan_in=fan_in,
                max_depth=max_depth,
                skip_regional_below=skip_regional,
            )
            regional = hierarchy.regional_texts_for_compile(levels)
            if regional:
                compile_inputs = regional
            compile_meta["hierarchy_depth"] = len(levels)
            compile_meta["hierarchy_fan_in"] = fan_in
            compile_meta["hierarchy"] = hierarchy.hierarchy_tree_for_ui(levels)

        medium_chain = list(settings.medium_models())
        heavy_chain = list(
            decision.get("compile_fallbacks") or settings.heavy_models()
        )
        hint = str(strat.get("compile_tier_hint") or "medium").lower()
        first_chain = (
            heavy_chain
            if hint == "heavy" and not strat.get("medium_first", True)
            else medium_chain
        )

        final_summary = ""
        final_verdict = quality_validation.ValidationVerdict(
            passed=False,
            confidence=0.0,
            faithfulness=0.0,
            coverage=0.0,
            hallucination_rate=1.0,
            contradiction_rate=0.0,
            codes=["compile_not_run"],
            details={},
        )
        compile_tau = float(
            strat.get("qva_compile_threshold")
            if strat.get("qva_compile_threshold") is not None
            else getattr(settings, "QVA_COMPILE_CONFIDENCE_THRESHOLD", 0.58) or 0.58
        )

        # --- DAG hierarchical compile (parallel regional/chapter/executive) ---
        use_dag = bool(getattr(settings, "DAG_COMPILE_ENABLED", True)) and len(
            state.get("summaries") or []
        ) >= 2
        if use_dag:
            try:
                from src.core import dag_scheduler

                def _dag_progress(pct: float, msg: str, extra: Dict[str, Any]) -> None:
                    _set_progress(job_id, pct, msg, force=True)
                    try:
                        job_store.JOB_STATUSES.setdefault(job_id, {})
                        partial = dict(job_store.JOB_STATUSES[job_id].get("partial") or {})
                        if isinstance(extra.get("dag"), dict):
                            partial["dag"] = extra["dag"]
                        job_store.JOB_STATUSES[job_id]["partial"] = partial
                    except Exception:
                        pass

                dag_deadline = time.monotonic() + min(
                    reduce_max, max(30.0, _node_remaining())
                )
                dag_t0 = time.perf_counter()
                dag_out = dag_scheduler.run_dag_compile(
                    state.get("chunks") or [],
                    state.get("summaries") or [],
                    state,
                    fan_in=fan_in,
                    max_depth=max_depth,
                    skip_regional_below=skip_regional,
                    medium_chain=medium_chain,
                    heavy_chain=heavy_chain,
                    medium_first=bool(
                        strat.get(
                            "medium_first",
                            getattr(settings, "COMPILE_MEDIUM_FIRST", True),
                        )
                    ),
                    qva_tau=compile_tau,
                    max_workers=settings.effective_compile_max_workers(),
                    deadline_mono=dag_deadline,
                    progress_cb=_dag_progress,
                    existing_nodes=_restore_pipeline_nodes(state),
                )
                final_summary = str(dag_out.get("final_summary") or "")
                compile_meta["medium_compile_ms"] = round(
                    (time.perf_counter() - dag_t0) * 1000.0, 1
                )
                compile_meta["compile_calls"] = int(dag_out.get("compile_calls") or 0)
                compile_meta["compile_carbon_g"] = float(
                    dag_out.get("compile_carbon_g") or 0.0
                )
                carbon_spent += float(dag_out.get("compile_carbon_g") or 0.0)
                compile_meta["used_heavy"] = bool(dag_out.get("used_heavy"))
                compile_meta["hierarchy"] = dag_out.get("hierarchy") or compile_meta.get(
                    "hierarchy"
                )
                compile_meta["dag_nodes"] = dag_out.get("dag_nodes") or {}
                compile_meta["dag_workers"] = dag_out.get("workers")
                compile_meta["endpoint_pool"] = dag_out.get("endpoint_pool") or []
                compile_meta["carbon_rollups"] = dag_out.get("carbon_rollups") or {}
                compile_meta["perf_metrics"] = dag_out.get("perf_metrics") or {}
                compile_meta["branch_recompiles"] = list(
                    dag_out.get("branch_recompiles") or []
                )
                compile_meta["engine"] = "dag"
                # Persist full graph back onto state for UI / finalize
                if dag_out.get("dag_nodes"):
                    state_nodes = dict(state.get("pipeline_dag_nodes") or {})
                    state_nodes.update(dag_out.get("dag_nodes") or {})
                    # returned via compile_meta; finalize merges insights
                    compile_meta["pipeline_dag_nodes"] = state_nodes
                qva_t0 = time.perf_counter()
                final_verdict = quality_validation.validate_final(
                    list(state.get("summaries") or [])[:40], final_summary
                )
                compile_meta["quality_check_ms"] = round(
                    (time.perf_counter() - qva_t0) * 1000.0, 1
                )
                use_dag = True  # completed
            except Exception as e:
                log.error("Job %s: DAG compile failed, falling back: %s", job_id, e)
                compile_meta["skipped_steps"].append(
                    {"step": "dag_compile", "reason": f"error:{type(e).__name__}"}
                )
                use_dag = False

        if not use_dag or not (final_summary or "").strip():
            compile_meta["engine"] = compile_meta.get("engine") or "legacy"
            try:
                final_summary = _compile_call(
                    "Compiling executive summary...",
                    82.0,
                    compile_inputs,
                    first_chain,
                    step_key="medium_compile_ms",
                )
            except Exception as e:
                log.error("Job %s: primary compile failed: %s", job_id, e)
                final_summary = models.stitch_compile_fallback(
                    compile_inputs, reason=str(e)[:160]
                )
                compile_meta["used_stitched_fallback"] = True
                compile_meta["skipped_steps"].append(
                    {"step": "primary_compile", "reason": f"error:{type(e).__name__}"}
                )

        # Legacy medium→heavy→repair path (skipped when DAG engine already ran)
        if compile_meta.get("engine") != "dag":
            qva_t0 = time.perf_counter()
            final_verdict = quality_validation.validate_final(
                compile_inputs, final_summary
            )
            compile_meta["quality_check_ms"] = round(
                (time.perf_counter() - qva_t0) * 1000.0, 1
            )
        need_heavy = (not final_verdict.passed) or (
            float(final_verdict.confidence) < compile_tau
        )
        if (
            compile_meta.get("engine") != "dag"
            and need_heavy
            and bool(
                strat.get("medium_first", getattr(settings, "COMPILE_MEDIUM_FIRST", True))
            )
            and not compile_meta["used_stitched_fallback"]
            and _can_start_expensive_repair(step="heavy_compile", min_sec=20.0)
        ):
            log.info("Job %s: medium compile QVA failed → heavy compile", job_id)
            try:
                final_summary = _compile_call(
                    "Heavy compile (quality gate)...",
                    86.0,
                    compile_inputs,
                    heavy_chain,
                    step_key="heavy_compile_ms",
                )
                final_verdict = quality_validation.validate_final(
                    compile_inputs, final_summary
                )
                compile_meta["used_heavy"] = True
                compile_meta["branch_recompiles"].append(
                    {
                        "branch": "global",
                        "reason": "compile_qva_failed_or_low_confidence",
                        "confidence": final_verdict.confidence,
                    }
                )
            except Exception as e:
                log.error("Job %s: heavy compile failed: %s", job_id, e)
                compile_meta["skipped_steps"].append(
                    {"step": "heavy_compile", "reason": f"error:{type(e).__name__}"}
                )

        # Branch-level repair: gated by node time ceiling AND carbon remaining.
        # (Does not affect map-stage QVA escalation — compile-only.)
        if (
            compile_meta.get("engine") != "dag"
            and levels
            and (not final_verdict.passed or float(final_verdict.confidence) < compile_tau)
            and len(compile_inputs) > 1
            and not compile_meta["used_stitched_fallback"]
            and _can_start_expensive_repair(step="branch_repair", min_sec=25.0)
        ):
            repair_t0 = time.perf_counter()
            scores = []
            for i, text in enumerate(compile_inputs):
                v = quality_validation.validate_pair(
                    text,
                    final_summary[: max(200, len(text) // 4)],
                    confidence_threshold=compile_tau,
                )
                scores.append((float(v.confidence), i))
            scores.sort()
            repaired_any = False
            for _, bi in scores[:2]:
                if not _can_start_expensive_repair(
                    step=f"branch_repair_{bi}", min_sec=15.0
                ):
                    break
                branch_text = compile_inputs[bi]
                try:
                    repaired = _compile_call(
                        f"Repairing weak branch {bi + 1}...",
                        88.0,
                        [branch_text],
                        heavy_chain,
                        step_key="branch_repair_ms",
                    )
                except Exception as e:
                    log.warning("Job %s: branch %s repair failed: %s", job_id, bi, e)
                    continue
                if repaired and repaired.strip():
                    compile_inputs[bi] = repaired
                    repaired_any = True
                    compile_meta["branch_recompiles"].append(
                        {
                            "branch": f"regional-{bi}",
                            "reason": "low_branch_confidence",
                            "confidence": scores[0][0] if scores else None,
                        }
                    )
            # If branch_repair_ms was overwritten by multiple calls, keep cumulative.
            compile_meta["branch_repair_ms"] = round(
                (time.perf_counter() - repair_t0) * 1000.0, 1
            )
            if repaired_any and _can_start_expensive_repair(
                step="global_recompile", min_sec=20.0
            ):
                try:
                    final_summary = _compile_call(
                        "Recompiling after branch repair...",
                        90.0,
                        compile_inputs,
                        heavy_chain,
                        step_key="global_recompile_ms",
                    )
                    final_verdict = quality_validation.validate_final(
                        compile_inputs, final_summary
                    )
                    compile_meta["used_heavy"] = True
                except Exception as e:
                    log.error("Job %s: global recompile failed: %s", job_id, e)
                    compile_meta["skipped_steps"].append(
                        {
                            "step": "global_recompile",
                            "reason": f"error:{type(e).__name__}",
                        }
                    )
            elif repaired_any:
                # Time/carbon blocked global recompile — keep repaired branches
                # but fall back to stitch if current summary is unusable.
                if not (final_summary or "").strip():
                    final_summary = models.stitch_compile_fallback(
                        compile_inputs, reason="global_recompile_skipped"
                    )
                    compile_meta["used_stitched_fallback"] = True

        # If we never got a usable LLM summary and still have inputs, stitch.
        if (
            not (final_summary or "").strip()
            or (
                compile_meta.get("skipped_steps")
                and "stitched fallback" not in (final_summary or "").lower()
                and not final_verdict.passed
                and float(final_verdict.confidence or 0) < 0.2
            )
        ):
            # Only force-stitch when confidence is near-zero / empty.
            if not (final_summary or "").strip():
                final_summary = models.stitch_compile_fallback(
                    compile_inputs, reason="reduce_compile_budget_or_failure"
                )
                compile_meta["used_stitched_fallback"] = True

        compile_meta["compile_confidence"] = final_verdict.confidence
        compile_meta["compile_passed"] = final_verdict.passed
        compile_meta["reduce_compile_elapsed_ms"] = round(
            (time.monotonic() - node_t0) * 1000.0, 1
        )
        lat.add_meta(
            compile_calls=compile_meta["compile_calls"],
            compile_carbon_g=compile_meta["compile_carbon_g"],
            medium_compile_ms=compile_meta.get("medium_compile_ms"),
            quality_check_ms=compile_meta.get("quality_check_ms"),
            heavy_compile_ms=compile_meta.get("heavy_compile_ms"),
            branch_repair_ms=compile_meta.get("branch_repair_ms"),
            global_recompile_ms=compile_meta.get("global_recompile_ms"),
        )

    # Refresh intelligence report
    intel = state.get("pipeline_intelligence") or {}
    if intel:
        from src.core.pipeline_intelligence import enrich_report_after_run

        intel = enrich_report_after_run(
            intel,
            routing_distribution=state.get("routing_distribution"),
            cre_result=state.get("cre_result"),
            escalations={
                "chunks_escalated": state.get("chunks_escalated"),
                "escalation_count": state.get("escalation_count"),
            },
            compile_meta=compile_meta,
            validation=final_verdict.to_dict(),
            latency_by_stage=(state.get("ingestion_latency") or {}).get("stages_ms"),
        )

    accept_warn = (
        bool(state.get("accept_with_warning"))
        or not final_verdict.passed
        or bool(compile_meta.get("used_stitched_fallback"))
        or bool(compile_meta.get("skipped_steps"))
    )
    return {
        "final_summary": final_summary,
        "validation_verdict": final_verdict.to_dict(),
        "accept_with_warning": accept_warn,
        "hierarchy": compile_meta.get("hierarchy") or {},
        "compile_meta": compile_meta,
        "pipeline_intelligence": intel or state.get("pipeline_intelligence"),
        "carbon_spent_g": round(carbon_spent, 4),
        "carbon_remaining_g": round(max(0.0, budget - carbon_spent), 4),
        "ingestion_latency": _persist_latency(lat),
    }


def execute_document_dag_node(state: AgentState) -> Dict[str, Any]:
    """
    Thin LangGraph entry: one continuous DAG executor owns map → QVA escalate →
    hierarchy compile. Replaces the split map/validate/escalate/reduce stages.
    """
    job_id = state["job_id"]
    lat = _get_latency(state)
    reduce_max = float(getattr(settings, "REDUCE_COMPILE_MAX_SEC", 270.0) or 270.0)
    map_hard = float(getattr(settings, "MAP_CHUNK_HARD_TIMEOUT_SEC", 90.0) or 90.0)
    compile_hard = float(getattr(settings, "COMPILE_NODE_HARD_TIMEOUT_SEC", 90.0) or 90.0)
    n_chunks = max(1, int(state.get("total_chunks") or len(state.get("chunks") or []) or 1))
    workers = max(1, int(settings.effective_parallel_workers()))
    map_attempts = max(2, int(getattr(settings, "MAP_EMPTY_RETRY_ATTEMPTS", 2) or 2))
    # Shared wall for the whole document DAG (map + escalate + compile).
    # Prior default (270s) was too tight: medium-tier NIM hangs + retries burned
    # the whole budget, then escalate/compile ran with a negative deadline and
    # wiped summaries → "Unable to generate a final summary…".
    waves = int(math.ceil(n_chunks / float(workers)))
    map_budget = map_hard * waves * min(map_attempts, 3)
    dag_wall = max(
        reduce_max,
        map_budget + compile_hard + 60.0,
        600.0,  # floor for live NIM flakiness on small docs
    )
    # Cap absurd walls but allow large docs
    dag_wall = min(dag_wall, float(getattr(settings, "JOB_MAX_RUNTIME_SEC", 7200.0) or 7200.0))
    deadline_mono = time.monotonic() + dag_wall

    log.info(
        "Job %s: [5–7] Unified DAG executor (wall=%.0fs chunks=%s workers=%s)",
        job_id,
        dag_wall,
        n_chunks,
        workers,
    )
    _set_progress(job_id, 35.0, "Running unified pipeline DAG...", force=True)

    from src.core.pipeline_executor import execute_document_dag

    def _progress(pct: float, msg: str, extra: Dict[str, Any]) -> None:
        # Throttle DB writes; in-memory partial DAG snapshot still updates every tick.
        _set_progress(job_id, pct, msg, force=False)
        try:
            job_store.JOB_STATUSES.setdefault(job_id, {})
            partial = dict(job_store.JOB_STATUSES[job_id].get("partial") or {})
            if isinstance(extra.get("dag"), dict):
                partial["dag"] = extra["dag"]
                d = extra["dag"]
                if d.get("workers_busy") is not None:
                    partial["workers_busy"] = d.get("workers_busy")
                if d.get("workers_total") is not None:
                    partial["workers_total"] = d.get("workers_total")
                if d.get("eta_sec") is not None:
                    partial["eta_sec"] = d.get("eta_sec")
                if d.get("carbon_g") is not None:
                    partial["carbon_g"] = d.get("carbon_g")
                if d.get("remaining") is not None:
                    partial["remaining_tasks"] = d.get("remaining")
                if d.get("avg_latency_ms") is not None:
                    partial["avg_latency_ms"] = d.get("avg_latency_ms")
            job_store.JOB_STATUSES[job_id]["partial"] = partial
        except Exception:
            pass

    with lat.stage(STAGE_MAP_SUMMARIZE):
        out = execute_document_dag(
            dict(state),
            progress_cb=_progress,
            deadline_mono=deadline_mono,
        )
    _set_progress(job_id, 88.0, "Unified pipeline DAG complete", force=True)
    for k, v in (out.get("stage_timings_ms") or {}).items():
        try:
            lat.add_meta(**{str(k): float(v)})
        except Exception:
            pass

    budget = float(state.get("carbon_budget_g") or settings.CARBON_BUDGET_G)
    carbon_spent = float(out.get("carbon_spent_g") or 0.0)
    compile_meta = dict(out.get("compile_meta") or {})
    final_summary = str(out.get("final_summary") or "")
    verdict = out.get("validation_verdict") or {}
    accept_warn = bool(
        not (verdict.get("passed") if isinstance(verdict, dict) else True)
        or compile_meta.get("used_stitched_fallback")
        or not (final_summary or "").strip()
    )
    if not (final_summary or "").strip():
        final_summary = models.stitch_compile_fallback(
            list(out.get("summaries") or [])[:40],
            reason="unified_dag_empty_final",
        )
        compile_meta["used_stitched_fallback"] = True
        accept_warn = True

    intel = state.get("pipeline_intelligence") or {}
    if intel:
        try:
            from src.core.pipeline_intelligence import enrich_report_after_run

            intel = enrich_report_after_run(
                intel,
                routing_distribution=state.get("routing_distribution"),
                cre_result=state.get("cre_result"),
                escalations={
                    "chunks_escalated": compile_meta.get("escalation_count"),
                    "escalation_count": compile_meta.get("escalation_count"),
                },
                compile_meta=compile_meta,
                validation=verdict if isinstance(verdict, dict) else {},
                latency_by_stage=(state.get("ingestion_latency") or {}).get("stages_ms"),
            )
        except Exception:
            pass

    lat.add_meta(unified_dag=True, compile_engine=compile_meta.get("engine"))
    return {
        "summaries": out.get("summaries") or [],
        "final_summary": final_summary,
        "agent_telemetry": out.get("agent_telemetry") or [],
        "carbon_spent_g": round(carbon_spent, 4),
        "carbon_remaining_g": round(max(0.0, budget - carbon_spent), 4),
        "pipeline_dag_nodes": out.get("pipeline_dag_nodes") or {},
        "compile_meta": compile_meta,
        "execution_plan": out.get("execution_plan") or {},
        "validation_verdict": verdict if isinstance(verdict, dict) else {},
        "accept_with_warning": accept_warn,
        "hierarchy": compile_meta.get("hierarchy") or {},
        "map_checkpoint": out.get("map_checkpoint") or {},
        "pipeline_intelligence": intel or state.get("pipeline_intelligence"),
        "ingestion_latency": _persist_latency(lat),
        "escalation_count": int(compile_meta.get("escalation_count") or 0),
    }


def deliver_summary(state: AgentState) -> Dict[str, Any]:
    """
    Publish final summary immediately (Summary Ready).

    Embedding / Chroma / BM25 / carbon / telemetry run as background services
    and must never block this node.
    """
    job_id = state["job_id"]
    final_summary = str(state.get("final_summary") or "")
    log.info("Job %s: [Summary Ready] delivering summary (%s chars)", job_id, len(final_summary))
    try:
        from src.core.sync_lifecycle import log_transition

        log_transition(job_id, "Summary Ready", detail={"chars": len(final_summary)})
    except Exception:
        pass
    _set_progress(job_id, 91.0, "Summary Ready", force=True)

    document_id = state.get("document_id") or job_id
    display_name = state.get("filename") or state.get("original_filename") or document_id
    rollups = (state.get("compile_meta") or {}).get("carbon_rollups") or state.get("carbon_rollups") or {}
    operational = float(
        rollups.get("total_carbon_g")
        or state.get("carbon_spent_g")
        or 0.0
    )
    result = {
        "document_id": document_id,
        "filename": display_name,
        "final_summary": final_summary,
        "job_id": job_id,
        "summary_ready": True,
        "background": {
            "phase": "queued",
            "message": "Background Indexing",
        },
        "carbon_data": {
            "carbon_saved_grams": 0.0,
            "efficiency_percent": 0.0,
            # Primary metric at Summary Ready: Operational CO₂e from DAG nodes
            "operational_co2e_g": operational,
            "actual_cost_gco2e": operational,
            "primary_metric": "operational_co2e",
            "modeled_co2e_g": None,
            "modeled_label": "Modeled CO₂e Estimate",
            "baseline_cost_gco2e": 0.0,
            "total_chunks": int(state.get("total_chunks") or 0),
            "processing_time_seconds": 0.0,
        },
        "hierarchy": state.get("hierarchy"),
        "routing_distribution": state.get("routing_distribution"),
        "chunk_routing": state.get("chunk_routing"),
        "compile_meta": state.get("compile_meta"),
        "execution_plan": state.get("execution_plan") or {},
        "ingestion_latency": state.get("ingestion_latency"),
        "accept_with_warning": bool(state.get("accept_with_warning")),
    }
    try:
        from src.core.processing_insights import build_processing_insights

        routing_decision = dict(state.get("routing_decision") or {})
        features = state.get("features") if isinstance(state.get("features"), dict) else {}
        if not routing_decision.get("document_type") and features.get("document_type"):
            routing_decision["document_type"] = features.get("document_type")
        result["processing_insights"] = build_processing_insights(
            routing_decision=routing_decision,
            cre_result=state.get("cre_result"),
            carbon_report={},
            validation_verdict=state.get("validation_verdict"),
            job_mode=state.get("job_mode") or "automatic",
            latency_ms=None,
            routing_distribution=state.get("routing_distribution"),
            chunk_routing=state.get("chunk_routing"),
            hierarchy=state.get("hierarchy"),
            agent_telemetry=state.get("agent_telemetry"),
            compile_meta=state.get("compile_meta"),
            carbon_budget_g=state.get("carbon_budget_g"),
            carbon_spent_g=state.get("carbon_spent_g"),
            carbon_remaining_g=state.get("carbon_remaining_g"),
            predicted_final_carbon_g=state.get("predicted_final_carbon_g"),
            ingestion_latency=state.get("ingestion_latency"),
            triage_meta=state.get("triage_meta"),
            pipeline_intelligence=state.get("pipeline_intelligence"),
        )
    except Exception as e:
        log.warning("Job %s: early processing_insights failed: %s", job_id, e)

    job_store.upsert_job(
        job_id,
        status=job_status_mod.STATUS_COMPLETE,
        progress=91.0,
        message="Summary Ready",
        result=result,
        result_source="orchestrator.deliver_summary",
        routing_decision=state.get("routing_decision"),
        selected_model=(state.get("routing_decision") or {}).get("selected_model"),
        crs=(state.get("cre_result") or {}).get("crs"),
    )
    try:
        from src.core.sync_lifecycle import log_transition

        log_transition(job_id, "Summary persisted", detail={"progress": 91.0})
    except Exception:
        pass
    try:
        job_store.JOB_STATUSES.setdefault(job_id, {})["background"] = result["background"]
        partial = dict(job_store.JOB_STATUSES[job_id].get("partial") or {})
        partial["background"] = result["background"]
        partial["summary_ready"] = True
        job_store.JOB_STATUSES[job_id]["partial"] = partial
    except Exception:
        pass

    # Off critical path
    try:
        from src.core.background_services import enqueue_post_summary_services
        from src.core.sync_lifecycle import log_transition

        enqueue_post_summary_services(job_id, dict(state))
        log_transition(job_id, "Background Started")
    except Exception as e:
        log.error("Job %s: failed to enqueue background services: %s", job_id, e)

    return {"summary_delivered": True}


def route_after_cre(state: AgentState) -> str:
    if bool(getattr(settings, "UNIFIED_DAG_EXECUTOR_ENABLED", True)):
        return "execute_document_dag"
    return "map_summarize"
def store_for_rag(state: AgentState) -> Dict[str, Any]:
    job_id = state["job_id"]
    log.info(f"Job {job_id}: [8] Storing for RAG...")
    _set_progress(job_id, 90.0, "Indexing for search...", force=True)
    lat = _get_latency(state)

    from src.perf.critical_path import CriticalPath, dag_audit_get

    cp = CriticalPath(job_id, label="post_dag")
    prefetched = None
    with cp.step("embed_prefetch_wait") as info:
        if bool(getattr(settings, "ENABLE_EMBED_PREFETCH", True)):
            try:
                from src.perf.prefetch import get_embed_prefetch

                prefetched = get_embed_prefetch(job_id, timeout_sec=90.0)
                info["prefetch_hit"] = bool(prefetched)
                info["prefetch_vectors"] = (
                    sum(1 for v in prefetched if v) if prefetched else 0
                )
                if prefetched:
                    lat.add_meta(embed_prefetch_hits=sum(1 for v in prefetched if v))
            except Exception as e:
                info["error"] = str(e)
                log.debug("embed prefetch retrieve failed: %s", e)
        else:
            info["skipped"] = True

    with lat.stage(STAGE_STORE):
        with cp.step("store_document_data") as info:
            try:
                t_store = time.perf_counter()
                storage.store_document_data(
                    job_id=job_id,
                    summary=state["final_summary"],
                    chunks=state["chunks"],
                    routing_decision=state.get("routing_decision"),
                    prefetched_embeddings=prefetched,
                )
                info["store_wall_ms"] = round((time.perf_counter() - t_store) * 1000.0, 2)
                info["chunk_count"] = len(state.get("chunks") or [])
                info["used_prefetch"] = bool(prefetched)
                log.info("Job %s: stored in Chroma / document store", job_id)
            except Exception as e:
                info["error"] = str(e)
                # Indexing failure should not orphan the job in processing — surface as
                # a hard failure so the runner marks error/retry.
                log.error("Job %s: store_for_rag failed: %s", job_id, e)
                raise

    try:
        lat.add_meta(**cp.as_meta())
        audit = dag_audit_get(job_id)
        if audit:
            lat.add_meta(
                dag_audit_submit_counts=dict(audit.get("submit_counts") or {}),
                dag_audit_overflow_inserts=len(audit.get("overflow_inserts") or []),
                dag_audit_deferred_overflow=len(audit.get("deferred_overflow") or []),
                dag_audit_misleading_executive_msgs=int(
                    audit.get("misleading_executive_msgs") or 0
                ),
                dag_audit_node_count_history=(audit.get("node_count_history") or [])[-20:],
            )
        for line in cp.format_table().splitlines():
            log.info("Job %s: %s", job_id, line)
    except Exception as e:
        log.debug("critical path meta skip: %s", e)

    return {"ingestion_latency": _persist_latency(lat)}


def finalize_metrics(state: AgentState) -> Dict[str, Any]:
    job_id = state["job_id"]
    log.info(f"Job {job_id}: [9] Carbon + telemetry...")
    _set_progress(job_id, 98.0, "Recording metrics...", force=True)
    from src.perf.critical_path import CriticalPath

    cp = CriticalPath(job_id, label="finalize")
    with cp.step("flush_progress"):
        try:
            from src.perf.progress import flush_progress

            flush_progress(job_id)
        except Exception:
            pass
    lat = _get_latency(state)

    with lat.stage(STAGE_FINALIZE):
        with cp.step("calculate_carbon_savings"):
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

        with cp.step("log_job_metrics"):
            metrics.log_job_metrics(job_id, report, state)

        latency = None
        if state.get("job_started_ms"):
            latency = (time.time() * 1000) - float(state["job_started_ms"])

        with cp.step("routing_telemetry"):
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

        # Avoid re-embedding / re-storing all chunks; patch carbon + routing only.
        with cp.step("update_document_carbon_meta"):
            try:
                storage.update_document_carbon_meta(
                    job_id=job_id,
                    summary=state["final_summary"],
                    carbon_meta=report,
                    routing_decision=decision or None,
                )
            except Exception as e:
                log.warning(
                    "Job %s: carbon meta patch failed (%s); falling back to store_document_data",
                    job_id,
                    e,
                )
                storage.store_document_data(
                    job_id=job_id,
                    summary=state["final_summary"],
                    chunks=[],
                    carbon_meta=report,
                    routing_decision=decision or None,
                )

    try:
        lat.add_meta(**cp.as_meta())
        for line in cp.format_table().splitlines():
            log.info("Job %s: %s", job_id, line)
    except Exception:
        pass

    ingestion_latency = lat.finish()
    log_ingestion_latency(job_id, ingestion_latency)
    table = format_latency_table(ingestion_latency)
    for line in table.splitlines():
        log.info("Job %s: %s", job_id, line)
    try:
        from src.perf.profiler import format_waterfall, rank_bottlenecks, attach_resource_snapshot

        stages = {
            k: float(v)
            for k, v in (ingestion_latency.get("stages") or {}).items()
            if isinstance(v, (int, float))
        }
        if ingestion_latency.get("total_ms") is not None:
            stages["total_ms"] = float(ingestion_latency["total_ms"])
        # Include DAG sub-stage timings from meta when present
        meta = ingestion_latency.get("meta") or {}
        for k in ("dag_map_ms", "dag_qva_escalate_ms", "dag_compile_ms"):
            if meta.get(k) is not None:
                stages[k] = float(meta[k])
        for line in format_waterfall(stages).splitlines():
            log.info("Job %s: %s", job_id, line)
        for row in rank_bottlenecks(stages):
            log.info(
                "Job %s: bottleneck #%s %s %.1fs (%.1f%%)",
                job_id,
                row["rank"],
                row["stage"],
                row["sec"],
                row["pct_of_stages"],
            )
        attach_resource_snapshot(ingestion_latency, label="finalize")
    except Exception as e:
        log.debug("waterfall profile skip: %s", e)

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

    # Never downgrade a Summary Ready / complete job back to processing.
    existing_status = None
    try:
        existing_status = (job_store.get_job(job_id) or job_store.JOB_STATUSES.get(job_id) or {}).get(
            "status"
        )
    except Exception:
        pass
    terminal = str(existing_status or "") in (
        job_status_mod.STATUS_COMPLETE,
        job_status_mod.STATUS_ERROR,
        job_status_mod.STATUS_CANCELLED,
    )
    job_store.upsert_job(
        job_id,
        progress=100.0,
        message=(
            "Summary Ready · Search available"
            if terminal
            else (
                "Job metrics recorded (accepted with warning). Finalizing results..."
                if state.get("accept_with_warning")
                else "Job metrics recorded. Finalizing results..."
            )
        ),
        status=job_status_mod.STATUS_COMPLETE if terminal else job_status_mod.STATUS_PROCESSING,
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
workflow.add_node("plan_pipeline", plan_pipeline)
workflow.add_node("cre_and_route", cre_and_route)
workflow.add_node("execute_document_dag", execute_document_dag_node)
workflow.add_node("deliver_summary", deliver_summary)
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
workflow.add_edge("extract_features", "plan_pipeline")
workflow.add_edge("plan_pipeline", "cre_and_route")
workflow.add_conditional_edges(
    "cre_and_route",
    route_after_cre,
    {
        "execute_document_dag": "execute_document_dag",
        "map_summarize": "map_summarize",
    },
)
# Critical path ends at Summary Ready; indexing/carbon run in background.
workflow.add_edge("execute_document_dag", "deliver_summary")
workflow.add_edge("deliver_summary", END)
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

workflow.add_edge("escalate_once", "validate_map")
workflow.add_edge("mark_warning", "reduce_compile")
workflow.add_edge("reduce_compile", "deliver_summary")
# store_for_rag / finalize_metrics remain callable from background_services
# (not on the LangGraph critical path for the unified DAG).
workflow.add_edge("store_for_rag", "finalize_metrics")
workflow.add_edge("finalize_metrics", END)

agentic_graph = workflow.compile()

log.info("Capability-Routed Agentic Graph compiled successfully.")
