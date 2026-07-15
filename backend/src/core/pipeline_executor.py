"""
Continuous pipeline DAG executor (Tasks 1–2).

Owns chunk → regional → chapter → executive execution in one capacity pool.
LangGraph nodes become thin entry/exit around ``execute_document_dag``.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from src.agents import models, quality_validation, summarization_agents
from src.core import dag_scheduler, pipeline_dag as pdag
from src.core.config import settings
from src.core.node_accounting import estimate_node_accounting
from src.core.node_assigner import assign_model_for_node, chain_for_tier, record_model_latency

log = logging.getLogger(__name__)

ProgressCb = Optional[Callable[[float, str, Dict[str, Any]], None]]


def _http_below_wall(*, role: str = "map") -> float:
    """HTTP read timeout strictly below the scheduler hard wall."""
    if role == "compile":
        http = float(getattr(settings, "NIM_COMPILE_TIMEOUT_SEC", 55.0) or 55.0)
        wall = float(getattr(settings, "COMPILE_NODE_HARD_TIMEOUT_SEC", 90.0) or 90.0)
    else:
        http = float(getattr(settings, "NIM_HTTP_TIMEOUT_SEC", 75.0) or 75.0)
        wall = float(getattr(settings, "MAP_CHUNK_HARD_TIMEOUT_SEC", 90.0) or 90.0)
    return max(1.0, min(http, wall - 1.0))


def _extractive_chunk_fallback(text: str, *, max_chars: int = 1400) -> str:
    """Deterministic summary when NIM map/escalate cannot produce usable text."""
    body = " ".join(str(text or "").split())
    if not body:
        return ""
    if len(body) > max_chars:
        cut = body[:max_chars]
        # Prefer a sentence/word boundary when truncating.
        for sep in (". ", "; ", ", ", " "):
            pos = cut.rfind(sep)
            if pos >= max_chars // 2:
                cut = cut[: pos + (1 if sep == ". " else 0)]
                break
        body = cut.rstrip() + "…"
    return (
        "## Extractive fallback\n\n"
        "_Model map/escalate did not return a usable summary; "
        "using source excerpt so compile can still proceed._\n\n"
        f"{body}"
    )


def _run_with_hard_isolation(
    fn: Callable[[], Any],
    *,
    hard_timeout_sec: float,
    label: str = "node",
) -> Any:
    """
    Run ``fn`` in a 1-thread pool with hard wall + non-blocking shutdown.
    Hung NIM sockets cannot stall the caller past ``hard_timeout_sec``.
    RateLimitBackpressure propagates immediately (not a hang).
    """
    import concurrent.futures

    from src.core.nim_rate_limit import RateLimitBackpressure, record_hard_isolation_timeout

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = pool.submit(fn)
    try:
        return fut.result(timeout=hard_timeout_sec)
    except RateLimitBackpressure:
        raise
    except concurrent.futures.TimeoutError as e:
        record_hard_isolation_timeout()
        log.warning(
            "Hard isolation timeout after %.0fs label=%s — abandoning thread",
            hard_timeout_sec,
            label,
        )
        try:
            fut.cancel()
        except Exception:
            pass
        raise TimeoutError(
            f"Node hard isolation timeout after {hard_timeout_sec:.0f}s ({label})"
        ) from e
    finally:
        models._shutdown_executor_nowait(pool, fut)


def execute_document_dag(
    state: dict,
    *,
    progress_cb: ProgressCb = None,
    deadline_mono: Optional[float] = None,
) -> Dict[str, Any]:
    """
    End-to-end DAG: map all chunk nodes → QVA escalate failed → hierarchy compile.

    Any idle worker may pull the next ready node (chunk or hierarchy).
    """
    from src.core.execution_scheduler import run_capacity_pool
    from src.core.nim_rate_limit import rate_limit_stats, reset_rate_limit_stats
    from src.db import jobs as job_store

    reset_rate_limit_stats()

    job_id = str(state.get("job_id") or "")
    chunks = list(state.get("chunks") or [])
    decision = state.get("routing_decision") or {}
    routes = {
        int(r.get("chunk_index", i)): r
        for i, r in enumerate(state.get("chunk_routing") or [])
    }
    intensity = float((state.get("features") or {}).get("grid_intensity") or 500.0)
    # Refresh live grid into features for assigner
    try:
        from src.core.node_assigner import refresh_live_grid_intensity

        intensity = refresh_live_grid_intensity(state)
    except Exception:
        pass

    strat = ((state.get("pipeline_intelligence") or {}).get("strategy") or {})
    profile = ((state.get("pipeline_intelligence") or {}).get("capability_profile") or {})
    fan_in = int(strat.get("hierarchy_fan_in") or getattr(settings, "COMPILE_BATCH_SIZE", 8) or 8)
    max_depth = int(strat.get("hierarchy_max_depth") or 12)
    skip_regional = int(strat.get("skip_regional_below") or 0)
    capability_score = float(
        profile.get("score")
        or profile.get("capability_score")
        or strat.get("capability_score")
        or 0.5
    )
    qva_tau = float(
        strat.get("qva_confidence_threshold")
        if strat.get("qva_confidence_threshold") is not None
        else getattr(settings, "QVA_CONFIDENCE_THRESHOLD", 0.60)
        or 0.60
    )
    compile_tau = float(
        strat.get("qva_compile_threshold")
        if strat.get("qva_compile_threshold") is not None
        else getattr(settings, "QVA_COMPILE_CONFIDENCE_THRESHOLD", 0.58)
        or 0.58
    )
    medium_first = bool(strat.get("medium_first", True))
    medium_chain = list(settings.medium_models())
    heavy_chain = list(settings.heavy_models())
    workers = max(1, int(settings.effective_parallel_workers()))
    map_hard = float(getattr(settings, "MAP_CHUNK_HARD_TIMEOUT_SEC", 90.0) or 90.0)
    compile_hard = float(getattr(settings, "COMPILE_NODE_HARD_TIMEOUT_SEC", 90.0) or 90.0)

    nodes = pdag.build_chunk_nodes(chunks, routes=routes)
    t0 = time.perf_counter()
    stage_timings_ms: Dict[str, float] = {}
    carbon_spent = float(state.get("carbon_spent_g") or 0.0)
    agent_telemetry: List[Dict[str, Any]] = list(state.get("agent_telemetry") or [])
    api_calls = 0

    # Overlap embedding with map/QVA/compile (immutable chunk text).
    if bool(getattr(settings, "ENABLE_EMBED_PREFETCH", True)) and job_id:
        try:
            from src.perf.prefetch import start_embed_prefetch

            start_embed_prefetch(job_id, chunks)
        except Exception as e:
            log.debug("embed prefetch skip in DAG: %s", e)

    def _emit(msg: str, pct: float) -> None:
        busy = sum(1 for n in nodes.values() if n.status == "running")
        snap = pdag.dag_progress_snapshot(nodes, workers_busy=busy, workers_total=workers)
        elapsed = time.perf_counter() - t0
        done = snap["completed"]
        rate = done / elapsed if elapsed > 0.5 and done else 0.0
        eta = (snap["remaining"] / rate) if rate > 0 else None
        snap["eta_sec"] = round(eta, 1) if eta is not None else None
        snap["carbon_g"] = round(
            sum(float(n.carbon_estimate_g or 0) for n in nodes.values()), 4
        )
        if progress_cb:
            progress_cb(pct, msg, {"dag": snap})
        if job_id:
            try:
                st = job_store.JOB_STATUSES.setdefault(job_id, {})
                partial = dict(st.get("partial") or {})
                partial["dag"] = snap
                partial["workers_busy"] = busy
                partial["workers_total"] = workers
                partial["avg_latency_ms"] = snap.get("avg_latency_ms")
                partial["carbon_g"] = snap.get("carbon_g")
                partial["remaining_tasks"] = snap.get("remaining")
                partial["eta_sec"] = snap.get("eta_sec")
                st["partial"] = partial
            except Exception:
                pass

    def _node_cancelled(nid: str) -> bool:
        try:
            cancels = set((job_store.JOB_STATUSES.get(job_id) or {}).get("node_cancels") or [])
            return nid in cancels
        except Exception:
            return False

    # Capture job wall before nested workers name their param ``deadline_mono``
    # (required so ``_supports_deadline`` returns True for the scheduler).
    job_deadline = deadline_mono

    def _deadline_remaining(task_deadline: Optional[float] = None) -> float:
        eff = task_deadline if task_deadline is not None else job_deadline
        if eff is None:
            return 1e9
        return float(eff) - time.monotonic()

    def _ok_result(idx: int, summary: str, *, tier: str, model_id: str, latency_ms: float = 0.0):
        return idx, summarization_agents.AgentRunResult(
            summary=summary,
            tier=tier,
            model_id=model_id,
            latency_ms=latency_ms,
            input_tokens=0,
            output_tokens=0,
            carbon_estimate_g=0.0,
            confidence=0.35 if model_id == "extractive_fallback" else 0.9,
            success=bool(summary),
        )

    # ---- Phase A: map all pending chunk nodes via unified pool ----
    t_map = time.perf_counter()
    def _run_chunk(payload, deadline_mono: Optional[float] = None):
        nonlocal carbon_spent, api_calls
        idx = int(payload) if not isinstance(payload, tuple) else int(payload[0])
        nid = f"chunk-{idx}"
        n = nodes[nid]
        if _node_cancelled(nid) or n.cancel_requested:
            n.cancel_requested = True
            n.status = "failed"
            return idx, None

        # Scheduler passes per-task lease; fall back to job wall.
        effective_deadline = deadline_mono if deadline_mono is not None else job_deadline
        remaining = _deadline_remaining(effective_deadline)
        src_text = n.input_text or (chunks[idx].content if idx < len(chunks) else "")

        # Near/past job wall: extractive fallback so compile always has input.
        if remaining < 8.0:
            fb = _extractive_chunk_fallback(src_text)
            n.output_summary = fb
            n.status = "completed" if fb else "failed"
            n.finished_at = time.monotonic()
            n.assigned_model = "extractive_fallback"
            agent_telemetry.append(
                {
                    "chunk_index": idx,
                    "phase": "map",
                    "success": bool(fb),
                    "model_id": "extractive_fallback",
                    "error": f"deadline_remaining={remaining:.1f}s",
                }
            )
            _emit(f"DAG map extractive fallback chunk {idx}", 40.0)
            return _ok_result(idx, fb, tier="light", model_id="extractive_fallback")

        n.status = "running"
        n.started_at = time.monotonic()
        _emit(f"DAG map — chunk {idx + 1}/{len(chunks)}", 35.0 + 25.0 * idx / max(1, len(chunks)))
        route = routes.get(idx) or {}
        tier = str(route.get("tier") or decision.get("tier") or "medium")
        chain = chain_for_tier(tier)
        assignment = assign_model_for_node(
            node_kind="chunk",
            min_tier=tier,
            model_chain=chain,
            state=state,
        )
        use_chain = list(chain)
        if assignment.get("model_id"):
            mid = assignment["model_id"]
            use_chain = [mid] + [m for m in use_chain if m != mid]
        n.assigned_model = assignment.get("model_id")
        n.tier = tier

        def _invoke():
            return summarization_agents.run_summarization_agent(
                src_text,
                state,
                tier=tier,
                model_ids=use_chain,
                grid_intensity=intensity,
                deadline_mono=effective_deadline,
                task_id=nid,
            )

        try:
            result = _run_with_hard_isolation(
                _invoke,
                hard_timeout_sec=map_hard,
                label=nid,
            )
            api_calls += 1
            record_model_latency(result.model_id or use_chain[0], float(result.latency_ms or 0))
            summary = (result.summary or "").strip()
            usable = bool(result.success) and models._is_usable_summary(summary)
            if not usable:
                # Soft NIM failure — pool may retry; if wall is nearly gone, fall back.
                if remaining < (map_hard + 5.0):
                    summary = _extractive_chunk_fallback(src_text)
                    usable = bool(summary)
                    result = summarization_agents.AgentRunResult(
                        summary=summary,
                        tier=tier,
                        model_id="extractive_fallback",
                        latency_ms=float(result.latency_ms or 0),
                        input_tokens=int(result.input_tokens or 0),
                        output_tokens=0,
                        carbon_estimate_g=0.0,
                        confidence=0.35,
                        success=usable,
                    )
                else:
                    n.retries += 1
                    n.status = "failed"
                    n.finished_at = time.monotonic()
                    agent_telemetry.append(
                        result.to_dict()
                        | {"chunk_index": idx, "phase": "map", "success": False}
                    )
                    return idx, result
            n.output_summary = summary
            n.latency_ms = float(result.latency_ms or 0)
            n.tokens_in = int(result.input_tokens or 0)
            n.tokens_out = int(result.output_tokens or 0)
            acct = estimate_node_accounting(
                tier=tier,
                tokens_in=n.tokens_in,
                tokens_out=n.tokens_out,
                latency_ms=n.latency_ms,
                grid_intensity=intensity,
                model_id=result.model_id,
            )
            n.carbon_estimate_g = float(acct["carbon_g"])
            n.energy_kwh = float(acct["energy_kwh"])
            n.cost_usd = float(acct["cost_usd"])
            n.assigned_model = result.model_id
            n.status = "completed" if usable else "failed"
            n.finished_at = time.monotonic()
            carbon_spent += n.carbon_estimate_g
            agent_telemetry.append(result.to_dict() | {"chunk_index": idx, "phase": "map"})
            _emit(f"DAG map completed {idx + 1}/{len(chunks)}", 40.0)
            return idx, result
        except Exception as e:
            from src.core.nim_rate_limit import RateLimitBackpressure, is_rate_limit_error

            if isinstance(e, RateLimitBackpressure) or is_rate_limit_error(e):
                n.status = "pending"
                n.retries += 1
                raise
            err_l = str(e).lower()
            if "deadline" in err_l or remaining < 8.0:
                fb = _extractive_chunk_fallback(src_text)
                n.output_summary = fb
                n.status = "completed" if fb else "failed"
                n.finished_at = time.monotonic()
                n.assigned_model = "extractive_fallback"
                agent_telemetry.append(
                    {
                        "chunk_index": idx,
                        "phase": "map",
                        "success": bool(fb),
                        "model_id": "extractive_fallback",
                        "error": str(e)[:300],
                    }
                )
                _emit(f"DAG map extractive fallback chunk {idx}", 40.0)
                return _ok_result(idx, fb, tier=tier, model_id="extractive_fallback")
            log.warning("Chunk node %s failed: %s", nid, e)
            n.retries += 1
            n.status = "failed"
            n.finished_at = time.monotonic()
            agent_telemetry.append(
                {"chunk_index": idx, "phase": "map", "success": False, "error": str(e)[:300]}
            )
            _emit(f"DAG map failed chunk {idx}", 40.0)
            return idx, None

    chunk_ids = [n.chunk_index for n in nodes.values() if n.kind == "chunk" and n.chunk_index is not None]
    chunk_ids.sort()
    _emit("DAG map starting", 35.0)

    def _chunk_ok(res) -> bool:
        if res is None:
            return False
        try:
            _i, r = res
        except Exception:
            return False
        if r is None or not bool(getattr(r, "success", True)):
            return False
        return models._is_usable_summary(getattr(r, "summary", "") or "")

    # Empty/hang retries stay modest; rate-limit uses its own ceiling inside the pool.
    map_attempts = max(1, int(getattr(settings, "MAP_EMPTY_RETRY_ATTEMPTS", 2) or 2))
    ordered, prog, mets = run_capacity_pool(
        chunk_ids,
        _run_chunk,
        role="map",
        kind="map",
        max_workers=workers,
        hard_timeout_sec=map_hard,
        max_attempts=map_attempts,
        is_success=_chunk_ok,
        on_progress=lambda p, m: _emit(p.message("DAG map"), 35.0 + 25.0 * p.completed / max(1, p.total)),
    )

    summaries = [""] * len(chunks)
    for idx in chunk_ids:
        nid = f"chunk-{idx}"
        summaries[idx] = nodes[nid].output_summary if nid in nodes else ""

    # Guarantee every chunk has usable text for compile (never blank stitch).
    for idx in chunk_ids:
        if models._is_usable_summary(summaries[idx]):
            continue
        src = nodes[f"chunk-{idx}"].input_text or (
            chunks[idx].content if idx < len(chunks) else ""
        )
        fb = _extractive_chunk_fallback(src)
        if not fb:
            continue
        summaries[idx] = fb
        nodes[f"chunk-{idx}"].output_summary = fb
        nodes[f"chunk-{idx}"].status = "completed"
        nodes[f"chunk-{idx}"].assigned_model = (
            nodes[f"chunk-{idx}"].assigned_model or "extractive_fallback"
        )

    stage_timings_ms["dag_map_ms"] = round((time.perf_counter() - t_map) * 1000.0, 2)

    # ---- Phase B: QVA + escalate failed chunks only (QVA is sole trigger) ----
    t_qva = time.perf_counter()
    failed_idx: List[int] = []
    try:
        verdict = quality_validation.validate_chunks(chunks, summaries, confidence_threshold=qva_tau)
        details = (verdict.details or {}) if hasattr(verdict, "details") else {}
        failed_idx = list(details.get("failed_indices") or [])
        empty_idx = [
            i for i, s in enumerate(summaries) if not models._is_usable_summary(s)
        ]
        # Only escalate empties / true QVA fails that are not already extractive.
        failed_idx = sorted(set(failed_idx) | set(empty_idx))
        state["validation_verdict"] = (
            verdict.to_dict() if hasattr(verdict, "to_dict") else {"passed": verdict.passed, "confidence": verdict.confidence, "details": details}
        )
    except Exception as e:
        log.warning("QVA map failed: %s", e)
        failed_idx = [
            i for i, s in enumerate(summaries) if not models._is_usable_summary(s)
        ]

    max_esc = int(strat.get("max_escalations") or getattr(settings, "QVA_MAX_ESCALATIONS", 2) or 2)
    max_esc_chunks = int(strat.get("max_escalate_chunks") or getattr(settings, "QVA_MAX_ESCALATE_CHUNKS", 8) or 8)
    esc_count = 0
    while failed_idx and esc_count < max_esc:
        # Skip escalate when the job wall cannot host another NIM call.
        if _deadline_remaining() < max(15.0, map_hard * 0.5):
            log.warning(
                "Skipping escalate: job deadline remaining=%.1fs",
                _deadline_remaining(),
            )
            break
        esc_count += 1
        batch = failed_idx[:max_esc_chunks]
        _emit(f"DAG escalate {esc_count}: {len(batch)} chunks", 62.0)

        def _esc_one(payload, deadline_mono: Optional[float] = None):
            nonlocal carbon_spent, api_calls
            idx = int(payload)
            nid = f"chunk-{idx}"
            n = nodes[nid]
            prior = (summaries[idx] or n.output_summary or "").strip()
            prior_usable = models._is_usable_summary(prior)
            effective_deadline = deadline_mono if deadline_mono is not None else job_deadline
            remaining = _deadline_remaining(effective_deadline)
            src_text = n.input_text or (chunks[idx].content if idx < len(chunks) else "")

            if remaining < 8.0:
                # Keep prior good text; otherwise extractive.
                keep = prior if prior_usable else _extractive_chunk_fallback(src_text)
                n.output_summary = keep
                summaries[idx] = keep
                n.status = "completed" if keep else "failed"
                return _ok_result(idx, keep, tier=str(n.tier or "medium"), model_id="extractive_fallback")

            n.status = "retrying"
            route = routes.get(idx) or {}
            cur = str(route.get("tier") or "medium")
            nxt = {"light": "medium", "medium": "heavy"}.get(cur, "heavy")
            chain = chain_for_tier(nxt)
            assignment = assign_model_for_node(
                node_kind="chunk", min_tier=nxt, model_chain=chain, state=state, prefer_quality=True
            )
            use_chain = list(chain)
            if assignment.get("model_id"):
                use_chain = [assignment["model_id"]] + [m for m in use_chain if m != assignment["model_id"]]

            def _invoke():
                return summarization_agents.run_summarization_agent(
                    src_text,
                    state,
                    tier=nxt,
                    model_ids=use_chain,
                    grid_intensity=intensity,
                    deadline_mono=effective_deadline,
                    task_id=f"esc-{nid}",
                )

            try:
                result = _run_with_hard_isolation(_invoke, hard_timeout_sec=map_hard, label=f"esc-{nid}")
                api_calls += 1
                record_model_latency(result.model_id or use_chain[0], float(result.latency_ms or 0))
                new_summary = (result.summary or "").strip()
                usable = bool(result.success) and models._is_usable_summary(new_summary)
                # NEVER wipe a usable prior summary with a failed escalate result.
                if usable:
                    n.output_summary = new_summary
                    summaries[idx] = new_summary
                    n.tier = nxt
                    n.status = "completed"
                    carbon_spent += float(result.carbon_estimate_g or 0)
                    agent_telemetry.append(result.to_dict() | {"chunk_index": idx, "phase": "escalate"})
                    return idx, result
                keep = prior if prior_usable else _extractive_chunk_fallback(src_text)
                n.output_summary = keep
                summaries[idx] = keep
                n.status = "completed" if keep else "failed"
                agent_telemetry.append(
                    (result.to_dict() if hasattr(result, "to_dict") else {})
                    | {"chunk_index": idx, "phase": "escalate", "success": False, "kept_prior": prior_usable}
                )
                return _ok_result(idx, keep, tier=nxt, model_id="extractive_fallback" if not prior_usable else (result.model_id or "prior"))
            except Exception as e:
                from src.core.nim_rate_limit import RateLimitBackpressure, is_rate_limit_error

                if isinstance(e, RateLimitBackpressure) or is_rate_limit_error(e):
                    n.status = "pending"
                    raise
                keep = prior if prior_usable else _extractive_chunk_fallback(src_text)
                n.output_summary = keep
                summaries[idx] = keep
                n.status = "completed" if keep else "failed"
                log.warning("Escalate %s failed (kept_prior=%s): %s", nid, prior_usable, e)
                return _ok_result(idx, keep, tier=str(n.tier or nxt), model_id="extractive_fallback" if not prior_usable else "prior")

        run_capacity_pool(
            batch,
            _esc_one,
            role="map",
            kind="map",
            max_workers=workers,
            hard_timeout_sec=map_hard,
            max_attempts=min(map_attempts, 3),
            is_success=_chunk_ok,
        )
        # Re-validate only escalated
        try:
            verdict = quality_validation.validate_chunks(
                chunks, summaries, confidence_threshold=qva_tau, only_indices=batch
            )
            details = (verdict.details or {}) if hasattr(verdict, "details") else {}
            failed_idx = list(details.get("failed_indices") or [])
        except Exception:
            failed_idx = [i for i in batch if not models._is_usable_summary(summaries[i])]

    stage_timings_ms["dag_qva_escalate_ms"] = round((time.perf_counter() - t_qva) * 1000.0, 2)

    # ---- Phase C: PLAN (freeze) then immutable compile ----
    t_compile = time.perf_counter()
    _emit("Planning", 80.0)
    from src.core.planning import plan_compile_hierarchy, format_execution_plan, assert_dag_immutable

    compile_workers = max(1, int(settings.effective_compile_max_workers()))
    nodes, exec_plan = plan_compile_hierarchy(
        nodes,
        chunks,
        summaries,
        job_id=job_id,
        fan_in=fan_in,
        max_depth=max_depth,
        skip_regional_below=skip_regional,
        map_workers=workers,
        compile_workers=compile_workers,
        qva_tau=qva_tau,
        compile_tau=compile_tau,
        medium_first=medium_first,
        intensity=intensity,
        capability_score=capability_score,
        adaptive_regional=True,
    )
    for line in format_execution_plan(exec_plan).splitlines():
        log.info("Job %s: %s", job_id, line)
    stage_timings_ms["plan_compile_ms"] = round((time.perf_counter() - t_compile) * 1000.0, 2)
    node_count_before = len(nodes)
    fingerprint_before = exec_plan.fingerprint

    _emit(
        f"Executing frozen DAG ({exec_plan.regional} regional, "
        f"{exec_plan.chapter} chapter, {exec_plan.executive} executive)…",
        82.0,
    )
    t_exec = time.perf_counter()
    dag_out = dag_scheduler.run_dag_compile(
        chunks,
        summaries,
        state,
        fan_in=fan_in,
        max_depth=max_depth,
        skip_regional_below=skip_regional,
        medium_chain=medium_chain,
        heavy_chain=heavy_chain,
        medium_first=medium_first,
        qva_tau=compile_tau,
        max_workers=compile_workers,
        deadline_mono=deadline_mono,
        progress_cb=lambda pct, msg, extra: _emit(msg, pct),
        existing_nodes=nodes,
        frozen_plan=exec_plan,
    )
    # Merge node dicts back
    for nid, d in (dag_out.get("dag_nodes") or {}).items():
        if isinstance(d, dict) and nid in nodes:
            for k, v in d.items():
                if hasattr(nodes[nid], k):
                    try:
                        setattr(nodes[nid], k, v)
                    except Exception:
                        pass

    assert_dag_immutable(nodes, exec_plan, phase="post_compile")
    from src.core.planning import fingerprint_topology

    fingerprint_after = fingerprint_topology(nodes)
    if fingerprint_after != fingerprint_before:
        raise RuntimeError(
            f"DAG fingerprint changed during execution: "
            f"{fingerprint_before} → {fingerprint_after}"
        )
    if len(nodes) != node_count_before:
        raise RuntimeError(
            f"DAG node count changed during execution: "
            f"{node_count_before} → {len(nodes)}"
        )
    stage_timings_ms["dag_compile_ms"] = round((time.perf_counter() - t_exec) * 1000.0, 2)
    stage_timings_ms["dag_total_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
    wall_ms = (time.perf_counter() - t0) * 1000.0
    rollups = pdag.carbon_rollups(nodes)
    metrics = pdag.perf_metrics(
        nodes,
        wall_ms=wall_ms,
        workers=workers,
        queue_wait_ms_avg=float((mets.to_dict() if mets else {}).get("avg_queue_wait_ms") or 0),
        api_calls=api_calls + int(dag_out.get("compile_calls") or 0),
        sequential_baseline_ms=sum(float(n.latency_ms or 0) for n in nodes.values()),
    )
    # Persist execution inspector artifact (replayable trace)
    try:
        from src.core.execution_inspector import write_execution_trace

        write_execution_trace(
            job_id,
            plan=exec_plan,
            nodes=nodes,
            dag_out=dag_out,
            stage_timings_ms=stage_timings_ms,
            rollups=rollups,
            metrics=metrics,
            fingerprint_before=fingerprint_before,
            fingerprint_after=fingerprint_after,
        )
    except Exception as e:
        log.warning("execution inspector write failed: %s", e)
    _emit("Summary Ready", 90.0)
    rl_stats = rate_limit_stats()
    sched_stats = mets.to_dict() if mets else {}

    return {
        "summaries": summaries,
        "final_summary": dag_out.get("final_summary") or "",
        "agent_telemetry": agent_telemetry,
        "carbon_spent_g": round(carbon_spent + float(dag_out.get("compile_carbon_g") or 0), 4),
        "pipeline_dag_nodes": {nid: n.to_dict() for nid, n in nodes.items()},
        "execution_plan": exec_plan.to_dict(),
        "compile_meta": {
            "engine": "unified_dag_frozen",
            "frozen": True,
            "fingerprint": fingerprint_before,
            "node_count": node_count_before,
            "compile_calls": dag_out.get("compile_calls"),
            "compile_carbon_g": dag_out.get("compile_carbon_g"),
            "used_heavy": dag_out.get("used_heavy"),
            "hierarchy": dag_out.get("hierarchy"),
            "dag_nodes": dag_out.get("dag_nodes"),
            "carbon_rollups": rollups,
            "perf_metrics": metrics,
            "branch_recompiles": dag_out.get("branch_recompiles") or [],
            "repair_report": dag_out.get("repair_report") or {},
            "escalation_count": esc_count,
            "rate_limit": rl_stats,
            "scheduler": sched_stats,
        },
        "validation_verdict": state.get("validation_verdict"),
        "map_checkpoint": {
            "completed_indices": [i for i, s in enumerate(summaries) if s],
            "summaries": summaries,
        },
        "perf_metrics": metrics,
        "carbon_rollups": rollups,
        "rate_limit": rl_stats,
        "scheduler": sched_stats,
        "stage_timings_ms": stage_timings_ms,
    }
