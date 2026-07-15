"""
Background services — off the critical path after Summary Ready.

Runs embeddings, Chroma/BM25 indexing, carbon aggregation, metrics, telemetry
asynchronously so the user receives the final summary immediately.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="bg-svc")
_LOCK = threading.Lock()
_JOB_FUTURES: Dict[str, Any] = {}


def enqueue_post_summary_services(job_id: str, state: dict) -> None:
    """Fire-and-forget post-summary work. Safe to call multiple times (deduped)."""
    with _LOCK:
        fut = _JOB_FUTURES.get(job_id)
        if fut is not None and not fut.done():
            log.info("Job %s: background services already running", job_id)
            return
        _JOB_FUTURES[job_id] = _EXECUTOR.submit(_run_post_summary, job_id, dict(state))
    log.info("Job %s: background services enqueued", job_id)


def _set_bg(job_id: str, phase: str, message: str, *, progress: Optional[float] = None) -> None:
    try:
        from src.db import jobs as job_store
        from src.core.sync_lifecycle import log_transition

        st = job_store.JOB_STATUSES.setdefault(job_id, {})
        bg = dict(st.get("background") or {})
        bg["phase"] = phase
        bg["message"] = message
        bg["updated_at"] = time.time()
        st["background"] = bg
        # Keep terminal status; only refresh message/partial for UI panel
        partial = dict(st.get("partial") or {})
        partial["background"] = bg
        st["partial"] = partial
        if progress is not None:
            # Do not downgrade progress below summary-ready floor
            cur = float(st.get("progress") or 0)
            st["progress"] = max(cur, float(progress))
        try:
            job_store.upsert_job(
                job_id,
                message=f"Summary Ready · {message}" if phase != "search_ready" else "Search Ready",
                progress=st.get("progress"),
            )
        except Exception:
            pass
        log_transition(
            job_id,
            {
                "embeddings": "Background Indexing",
                "indexing": "Background Indexing",
                "carbon": "Carbon Finished",
                "analytics": "Background Processing",
                "search_ready": "Search Indexed",
                "error": "Background Error",
            }.get(phase, f"Background:{phase}"),
            detail={"phase": phase, "message": message, "progress": st.get("progress")},
        )
    except Exception as e:
        log.debug("bg progress skip: %s", e)


def _run_post_summary(job_id: str, state: dict) -> Dict[str, Any]:
    from src.perf.critical_path import CriticalPath

    cp = CriticalPath(job_id, label="background")
    report: Dict[str, Any] = {"job_id": job_id, "ok": True}
    try:
        _set_bg(job_id, "indexing", "Preparing search index…", progress=92.0)

        with cp.step("embed_and_store"):
            _set_bg(job_id, "embeddings", "Generating embeddings…", progress=93.0)
            try:
                from src.core import orchestrator as orch

                # Reuse store_for_rag logic without blocking the graph
                orch.store_for_rag(state)
            except Exception as e:
                log.error("Job %s: background store failed: %s", job_id, e)
                report["store_error"] = str(e)

        with cp.step("finalize_metrics"):
            _set_bg(job_id, "carbon", "Updating carbon metrics…", progress=96.0)
            try:
                from src.core import orchestrator as orch

                out = orch.finalize_metrics(state)
                if isinstance(out, dict) and out.get("carbon_report"):
                    _patch_result_carbon(job_id, out["carbon_report"], state)
            except Exception as e:
                log.error("Job %s: background finalize failed: %s", job_id, e)
                report["finalize_error"] = str(e)

        with cp.step("analytics"):
            _set_bg(job_id, "analytics", "Finishing analytics…", progress=98.0)

        _set_bg(job_id, "search_ready", "Search available", progress=100.0)
        report["breakdown"] = cp.as_meta()
        for line in cp.format_table().splitlines():
            log.info("Job %s: %s", job_id, line)
    except Exception as e:
        report["ok"] = False
        report["error"] = str(e)
        _set_bg(job_id, "error", f"Background failed: {e}")
        log.exception("Job %s: background services crashed", job_id)
    return report


def _patch_result_carbon(job_id: str, carbon_report: dict, state: dict) -> None:
    """Merge carbon into already-published result without clearing the summary."""
    try:
        from src.db import jobs as job_store
        from src.core import job_status as job_status_mod
        from src.core.carbon_result_merge import (
            CARBON_FINALIZE_WIN_KEYS,
            additive_dict_merge,
            promote_carbon_from_region_decision,
        )
        from src.core.processing_insights import build_processing_insights

        job = job_store.get_job(job_id) or job_store.JOB_STATUSES.get(job_id) or {}
        result = dict(job.get("result") or {})
        # Never clear or overwrite the delivered summary
        summary = result.get("final_summary") or state.get("final_summary")
        if summary:
            result["final_summary"] = summary
        result["summary_ready"] = True

        cd = dict(result.get("carbon_data") or {})
        operational = cd.get("operational_co2e_g")
        if operational is None:
            rollups = (state.get("compile_meta") or {}).get("carbon_rollups") or {}
            operational = rollups.get("total_carbon_g") or state.get("carbon_spent_g")

        # Additive merge of full accounting payload (not a short allow-list).
        cd = additive_dict_merge(
            cd,
            carbon_report if isinstance(carbon_report, dict) else {},
            overlay_wins_keys=CARBON_FINALIZE_WIN_KEYS,
        )

        # Primary = Operational CO₂e; modeled estimate is secondary.
        modeled = carbon_report.get("actual_cost_gco2e") if isinstance(carbon_report, dict) else None
        if operational is not None:
            cd["operational_co2e_g"] = float(operational)
            cd["actual_cost_gco2e"] = float(operational)
            cd["primary_metric"] = "operational_co2e"
        if modeled is not None:
            cd["modeled_co2e_g"] = float(modeled)
            cd["modeled_label"] = "Modeled CO₂e Estimate"
            # Keep estimated_* aligned with modeled when present
            cd["estimated_optimized_pipeline_emissions_g"] = float(modeled)
        if isinstance(carbon_report, dict):
            if "baseline_cost_gco2e" in carbon_report:
                cd["estimated_baseline_pipeline_emissions_g"] = carbon_report["baseline_cost_gco2e"]
            if "carbon_saved_grams" in carbon_report:
                cd["estimated_carbon_saved_g"] = carbon_report["carbon_saved_grams"]
            if "efficiency_percent" in carbon_report:
                cd["estimated_reduction_percent"] = carbon_report["efficiency_percent"]

        cd = promote_carbon_from_region_decision(cd)
        result["carbon_data"] = cd

        # Preserve routing / hierarchy produced on the critical path
        for key in (
            "routing_distribution",
            "chunk_routing",
            "compile_meta",
            "hierarchy",
            "execution_plan",
            "ingestion_latency",
        ):
            state_val = state.get(key)
            existing = result.get(key)
            if state_val in (None, {}, []):
                continue
            if existing in (None, {}, []):
                result[key] = state_val
            elif isinstance(existing, dict) and isinstance(state_val, dict):
                result[key] = additive_dict_merge(existing, state_val)
            elif key in ("routing_distribution", "chunk_routing", "compile_meta"):
                result[key] = state_val

        # Refresh processing insights with finalized carbon — additive vs Summary Ready
        try:
            routing_decision = dict(state.get("routing_decision") or {})
            features = state.get("features") if isinstance(state.get("features"), dict) else {}
            if not routing_decision.get("document_type") and features.get("document_type"):
                routing_decision["document_type"] = features.get("document_type")
            fresh_pi = build_processing_insights(
                routing_decision=routing_decision,
                cre_result=state.get("cre_result"),
                carbon_report=carbon_report if isinstance(carbon_report, dict) else {},
                validation_verdict=state.get("validation_verdict"),
                job_mode=state.get("job_mode") or "automatic",
                latency_ms=None,
                routing_distribution=result.get("routing_distribution")
                or state.get("routing_distribution"),
                chunk_routing=result.get("chunk_routing") or state.get("chunk_routing"),
                hierarchy=result.get("hierarchy") or state.get("hierarchy"),
                agent_telemetry=state.get("agent_telemetry"),
                compile_meta=result.get("compile_meta") or state.get("compile_meta"),
                carbon_budget_g=state.get("carbon_budget_g"),
                carbon_spent_g=state.get("carbon_spent_g"),
                carbon_remaining_g=state.get("carbon_remaining_g"),
                predicted_final_carbon_g=state.get("predicted_final_carbon_g"),
                ingestion_latency=result.get("ingestion_latency")
                or state.get("ingestion_latency"),
                triage_meta=state.get("triage_meta"),
                pipeline_intelligence=state.get("pipeline_intelligence"),
            )
            result["processing_insights"] = additive_dict_merge(
                result.get("processing_insights")
                if isinstance(result.get("processing_insights"), dict)
                else {},
                fresh_pi,
                overlay_wins_keys={
                    "routing_distribution",
                    "chunk_routing_sample",
                    "escalation",
                    "document_type",
                    "document_profile",
                    "processing_strategy",
                    "intelligence_report",
                    "confidence",
                    "average_confidence",
                    "reason_summary",
                    "selected_model",
                    "tier",
                    "crs",
                },
            )
        except Exception as e:
            log.warning("Job %s: processing_insights refresh failed: %s", job_id, e)

        result["background"] = {"phase": "search_ready", "message": "Search Ready"}
        bg = (job_store.JOB_STATUSES.get(job_id) or {}).get("background") or {}
        if isinstance(bg, dict) and bg.get("phase"):
            result["background"] = bg
        job_store.upsert_job(
            job_id,
            status=job_status_mod.STATUS_COMPLETE,
            result=result,
            result_source="background_services._patch_result_carbon",
            carbon_saved_grams=cd.get("carbon_saved_grams"),
            message="Search Ready",
            progress=100.0,
        )
        try:
            from src.core.sync_lifecycle import log_transition

            log_transition(
                job_id,
                "Final Result Persisted",
                detail={
                    "phase": "search_ready",
                    "total_chunks": cd.get("total_chunks"),
                    "baseline": cd.get("baseline_cost_gco2e"),
                    "operational": cd.get("operational_co2e_g") or cd.get("actual_cost_gco2e"),
                    "grid": cd.get("local_grid_gco2_kwh"),
                    "region": cd.get("compute_location"),
                    "has_pi": bool(result.get("processing_insights")),
                    "has_routing": bool(result.get("routing_distribution")),
                },
            )
            log_transition(job_id, "Background Complete")
        except Exception:
            pass
    except Exception as e:
        log.warning("Job %s: patch result carbon failed: %s", job_id, e)


def background_status(job_id: str) -> Dict[str, Any]:
    try:
        from src.db import jobs as job_store

        return dict((job_store.JOB_STATUSES.get(job_id) or {}).get("background") or {})
    except Exception:
        return {}
