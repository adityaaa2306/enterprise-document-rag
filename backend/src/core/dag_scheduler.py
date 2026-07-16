"""
Hierarchical DAG compile engine (unified with pipeline_dag schema).

Map chunk nodes are real graph citizens (see pipeline_dag.build_chunk_nodes).
Compile nodes execute through the same MAX_PARALLEL_WORKERS capacity pool as map.
Medium→QVA→optional heavy enhancement in _compile_node_text is monotonic:
a successful executive summary is never replaced by stitch or failure.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

from src.agents import models, quality_validation
from src.chunking.service import estimate_tokens
from src.core import hierarchy as hierarchy_mod
from src.core import pipeline_dag as pdag
from src.core.config import settings
from src.core.node_accounting import estimate_node_accounting
from src.core.node_assigner import assign_model_for_node
from src.core.priority_queue import priority_for_kind

log = logging.getLogger(__name__)

ProgressCb = Optional[Callable[[float, str, Dict[str, Any]], None]]

# Re-export unified schema
DagNode = pdag.DagNode
_context_token_budget = pdag.context_token_budget


def compute_compile_budget_timeline(
    *,
    now_mono: float,
    absolute_job_deadline_mono: Optional[float],
    reserved_sec: float,
    per_task_hard_sec: float,
) -> Dict[str, Any]:
    """
    Exclusive compile-budget ownership timeline.

    Map / regional / chapter share the pre-reserve window ending at
    ``absolute_job_deadline - reserved``. Executive / final own a fresh
    ``reserved_sec`` wall starting when they run — never
    ``min(remaining_job_wall, reserved)``.
    """
    reserved = max(0.0, float(reserved_sec))
    hard = max(0.0, float(per_task_hard_sec))
    abs_dl = (
        float(absolute_job_deadline_mono)
        if absolute_job_deadline_mono is not None
        else None
    )
    pre_ceiling = (abs_dl - reserved) if abs_dl is not None else None

    def _pre_stage(label: str) -> Dict[str, Any]:
        # Per-task lease is hard timeout, clamped to the pre-executive ceiling.
        lease_end = now_mono + hard
        if pre_ceiling is not None:
            lease_end = min(lease_end, pre_ceiling)
        remaining = max(0.0, lease_end - now_mono)
        return {
            "stage": label,
            "deadline_mono": lease_end if abs_dl is not None or pre_ceiling is not None else None,
            "remaining_sec": remaining if abs_dl is not None else hard,
            "ceiling": "pre_executive",
            "owns_reserved_budget": False,
        }

    # Executive/final: exclusive reserved wall from *now* — not job remainder.
    exec_end = now_mono + reserved
    final_end = now_mono + reserved
    return {
        "now_mono": now_mono,
        "absolute_job_deadline_mono": abs_dl,
        "pre_executive_ceiling_mono": pre_ceiling,
        "reserved_sec": reserved,
        "absolute_remaining_sec": (abs_dl - now_mono) if abs_dl is not None else None,
        "stages": {
            "map": _pre_stage("map"),
            "regional": _pre_stage("regional"),
            "chapter": _pre_stage("chapter"),
            "executive": {
                "stage": "executive",
                "deadline_mono": exec_end,
                "remaining_sec": reserved,
                "ceiling": "exclusive_reserved",
                "owns_reserved_budget": True,
            },
            "final": {
                "stage": "final",
                "deadline_mono": final_end,
                "remaining_sec": reserved,
                "ceiling": "exclusive_reserved",
                "owns_reserved_budget": True,
            },
        },
    }


def phase_deadline_mono(
    kind: str,
    *,
    now_mono: float,
    absolute_job_deadline_mono: Optional[float],
    pre_executive_ceiling_mono: Optional[float],
    reserved_sec: float,
    per_task_lease_mono: Optional[float] = None,
) -> Optional[float]:
    """Resolve the wall-clock deadline for a DAG node kind."""
    if kind in ("executive", "final"):
        # Exclusive: full reserved window from this moment. Do NOT clamp to
        # remaining absolute job wall — that reintroduces shared-deadline starvation.
        return float(now_mono) + float(reserved_sec)
    d = per_task_lease_mono
    if d is None and absolute_job_deadline_mono is not None:
        d = float(absolute_job_deadline_mono)
    if d is None:
        return None
    d = float(d)
    if pre_executive_ceiling_mono is not None:
        d = min(d, float(pre_executive_ceiling_mono))
    return d


def build_compile_dag(
    chunks: Sequence[Any],
    summaries: Sequence[str],
    *,
    fan_in: int = 8,
    max_depth: int = 12,
    skip_regional_below: int = 0,
    existing_nodes: Optional[Dict[str, DagNode]] = None,
) -> Dict[str, DagNode]:
    """
    Build compile hierarchy on top of chunk nodes.
    If existing_nodes provided (from map stage), reuse those chunk nodes.
    """
    nodes = dict(existing_nodes or {})
    if not nodes:
        # Create completed chunk stubs from summaries (legacy compile-only entry)
        for i, s in enumerate(summaries):
            text = str(s or "")
            if not text.strip():
                continue
            nid = f"chunk-{i}"
            nodes[nid] = DagNode(
                id=nid,
                kind="chunk",
                depth=0,
                status="completed",
                output_summary=text,
                input_text=text,
                token_estimate=estimate_tokens(text),
                chunk_index=i,
            )
    return pdag.build_hierarchy_onto_chunks(
        nodes,
        chunks,
        summaries,
        fan_in=fan_in,
        max_depth=max_depth,
        skip_regional_below=skip_regional_below,
    )


def _compile_status_base() -> Dict[str, Any]:
    return {
        "compile_status": "pending",
        "compile_attempts": [],
        "best_compile_model": None,
        "heavy_compile_skipped": None,
        "summary_source": None,
    }


def _compile_node_text(
    text: str,
    *,
    medium_chain: List[str],
    heavy_chain: List[str],
    medium_first: bool,
    qva_tau: float,
    deadline_mono: Optional[float],
    state: dict,
    assigned_model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Medium-first compile + optional heavy enhancement for one node.

    Invariant: a successful executive summary is only replaced by a strictly
    better successful executive summary — never by stitch, timeout, or failure.
    """
    status = _compile_status_base()
    # Guard: if somehow still oversized, refuse to concat-split; stitch instead
    budget = _context_token_budget()
    if estimate_tokens(text) > int(budget * 1.15):
        log.warning(
            "Compile node input still over budget (%s > %s) — stitching",
            estimate_tokens(text),
            budget,
        )
        stitched = models.stitch_compile_fallback([text], reason="over_budget_no_split")
        status.update(
            {
                "compile_status": "stitched_fallback",
                "summary_source": "stitched_fallback",
                "compile_attempts": [{"phase": "over_budget", "result": "stitched"}],
            }
        )
        return {
            "summary": stitched,
            "used_heavy": False,
            "confidence": 0.4,
            "carbon_g": 0.0,
            "energy_kwh": 0.0,
            "tokens_in": estimate_tokens(text),
            "tokens_out": estimate_tokens(stitched),
            "cost_usd": 0.0,
            "latency_ms": 0.0,
            "model": None,
            "tier": "medium",
            "qva_passed": False,
            "compile_status": status,
        }

    used_heavy = False
    model_used = assigned_model
    best_summary: Optional[str] = None
    best_model: Optional[str] = None
    t0 = time.perf_counter()
    intensity = float((state.get("features") or {}).get("grid_intensity") or 500.0)
    enhance_min_sec = 15.0

    def _remaining() -> float:
        if deadline_mono is None:
            return 1e9
        return float(deadline_mono) - time.monotonic()

    def _try_compile(prompt: str, chain: List[str], *, phase: str) -> Optional[str]:
        """Run one compile chain; return durable executive text or None (stitch/fail)."""
        nonlocal model_used
        use_chain = list(chain)
        if assigned_model and assigned_model in use_chain:
            use_chain = [assigned_model] + [m for m in use_chain if m != assigned_model]
        elif assigned_model and phase == "medium":
            use_chain = [assigned_model] + use_chain
        attempt: Dict[str, Any] = {
            "phase": phase,
            "chain_head": use_chain[0] if use_chain else None,
            "budget_sec": round(_remaining(), 2),
        }
        try:
            out = models.run_compile_with_models(
                [prompt],
                state,
                use_chain,
                deadline_mono=deadline_mono,
            )
            out = models.strip_outer_markdown_fence(out)
            used = None
            if state.get("models_used"):
                used = (state.get("models_used") or [None])[-1]
                model_used = used or model_used
            if models.is_executive_compile_success(out):
                attempt["result"] = "success"
                attempt["model"] = used
                status["compile_attempts"].append(attempt)
                return out
            attempt["result"] = "stitched_or_unusable"
            attempt["model"] = used
            status["compile_attempts"].append(attempt)
            log.info(
                "Compile %s produced non-durable output (stitch/unusable); not adopting",
                phase,
            )
            return None
        except Exception as e:
            attempt["result"] = "error"
            attempt["error"] = str(e)[:160]
            status["compile_attempts"].append(attempt)
            log.warning("Compile %s failed: %s", phase, e)
            return None

    def _adopt(summary: str, *, model: Optional[str], source: str) -> None:
        nonlocal best_summary, best_model
        best_summary = summary
        best_model = model or best_model
        status["best_compile_model"] = best_model
        status["summary_source"] = source

    # --- Primary compile (medium-first or heavy-only) ---
    primary_chain = medium_chain if medium_first else heavy_chain
    primary_phase = "medium" if medium_first else "heavy"
    primary = _try_compile(text, primary_chain, phase=primary_phase)
    if primary:
        _adopt(primary, model=model_used, source="executive_compile")
        status["compile_status"] = "ok"
        if not medium_first:
            used_heavy = True

    if best_summary:
        verdict = quality_validation.validate_final([text], best_summary)
    else:
        verdict = quality_validation.ValidationVerdict(
            passed=False,
            confidence=0.0,
            faithfulness=0.0,
            coverage=0.0,
            hallucination_rate=1.0,
            contradiction_rate=0.0,
            codes=["no_executive_compile"],
            details={"reason": "no_executive_compile"},
        )

    # --- Optional heavy enhancement (never degrades best) ---
    if medium_first and best_summary:
        needs_enhance = (not verdict.passed) or float(verdict.confidence) < qva_tau
        if needs_enhance:
            rem = _remaining()
            if rem > enhance_min_sec:
                heavy_out = _try_compile(text, heavy_chain, phase="heavy_enhance")
                if heavy_out:
                    _adopt(heavy_out, model=model_used, source="executive_compile")
                    used_heavy = True
                    status["compile_status"] = "ok"
                    status["heavy_compile_skipped"] = None
                    verdict = quality_validation.validate_final([text], best_summary)
                else:
                    # Keep medium success — failures must not overwrite.
                    status["heavy_compile_skipped"] = "compile_failed"
                    status["compile_status"] = "degraded_enhance_failed"
                    log.info(
                        "Heavy enhance failed/skipped; keeping best executive "
                        "(model=%s)",
                        status.get("best_compile_model"),
                    )
            else:
                status["heavy_compile_skipped"] = "deadline_budget"
                status["compile_status"] = "degraded_timeout"
                status["compile_attempts"].append(
                    {
                        "phase": "heavy_enhance",
                        "result": "skipped",
                        "reason": "deadline_budget",
                        "budget_sec": round(rem, 2),
                    }
                )
                log.info(
                    "Heavy enhance skipped (remaining=%.1fs); keeping best executive",
                    rem,
                )

    # Stitch only when no executive compile succeeded at all.
    if not best_summary:
        best_summary = models.stitch_compile_fallback(
            [text], reason="all_executive_compile_failed"
        )
        status["compile_status"] = "stitched_fallback"
        status["summary_source"] = "stitched_fallback"
        status["best_compile_model"] = None
        verdict = quality_validation.ValidationVerdict(
            passed=False,
            confidence=0.35,
            faithfulness=0.0,
            coverage=0.0,
            hallucination_rate=1.0,
            contradiction_rate=0.0,
            codes=["stitched_fallback"],
            details={"reason": "stitched_fallback"},
        )

    latency_ms = (time.perf_counter() - t0) * 1000.0
    tier = "heavy" if used_heavy else "medium"
    tokens_in = estimate_tokens(text)
    tokens_out = estimate_tokens(best_summary or "")
    acct = estimate_node_accounting(
        tier=tier,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=latency_ms,
        grid_intensity=intensity,
        model_id=best_model or model_used,
    )
    return {
        "summary": models.strip_outer_markdown_fence(best_summary or ""),
        "used_heavy": used_heavy,
        "confidence": float(verdict.confidence),
        "carbon_g": acct["carbon_g"],
        "energy_kwh": acct["energy_kwh"],
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": acct["cost_usd"],
        "latency_ms": latency_ms,
        "model": best_model or model_used,
        "tier": tier,
        "qva_passed": bool(verdict.passed),
        "compile_status": status,
    }


def _safe_pool_snapshot() -> List[Dict[str, Any]]:
    try:
        from src.agents import nim_endpoint_pool as pool

        return pool.pool_snapshot()
    except Exception:
        return []


def _apply_result(n: DagNode, result: Dict[str, Any], *, worker_id: str = "") -> None:
    n.output_summary = result["summary"]
    n.used_heavy = bool(result.get("used_heavy"))
    n.qva_confidence = float(result.get("confidence") or 0.0)
    n.carbon_estimate_g = float(result.get("carbon_g") or 0.0)
    n.energy_kwh = float(result.get("energy_kwh") or 0.0)
    n.tokens_in = int(result.get("tokens_in") or 0)
    n.tokens_out = int(result.get("tokens_out") or 0)
    n.cost_usd = float(result.get("cost_usd") or 0.0)
    n.latency_ms = float(result.get("latency_ms") or 0.0)
    n.assigned_model = result.get("model")
    n.tier = result.get("tier")
    n.worker_id = worker_id or n.worker_id
    n.status = "completed" if (n.output_summary or "").strip() else "failed"
    n.finished_at = time.monotonic()


def recompute_branch(
    nodes: Dict[str, DagNode],
    node_id: str,
    *,
    state: dict,
    medium_chain: List[str],
    heavy_chain: List[str],
    medium_first: bool,
    qva_tau: float,
    deadline_mono: Optional[float],
) -> List[str]:
    """
    Recompute only this node and ancestors whose deps include it (Task 12).
    Never recomputes unrelated branches.
    """
    if node_id not in nodes:
        return []
    touched = [node_id]
    # Walk ancestors via children_ids reverse: parents list
    frontier = list(nodes[node_id].children_ids)
    seen = {node_id}
    while frontier:
        cid = frontier.pop()
        if cid in seen or cid not in nodes:
            continue
        seen.add(cid)
        touched.append(cid)
        frontier.extend(nodes[cid].children_ids)

    for tid in touched:
        n = nodes[tid]
        if n.kind == "chunk":
            continue
        n.status = "pending"
        n.output_summary = ""
        n.retries = 0

    # Execute touched non-chunk nodes in depth order.
    # NEVER call ensure_prompt_budget here — topology must stay immutable.
    compile_ids = [t for t in touched if nodes[t].kind != "chunk"]
    compile_ids.sort(key=lambda i: nodes[i].depth)
    for tid in compile_ids:
        n = nodes[tid]
        parts = [
            nodes[d].output_summary or nodes[d].input_text
            for d in n.dep_ids
            if d in nodes
        ]
        n.input_text = "\n\n".join(parts)
        n.status = "running"
        n.started_at = time.monotonic()
        try:
            assignment = assign_model_for_node(
                node_kind=n.kind,
                min_tier="medium",
                model_chain=medium_chain,
                state=state,
                prefer_quality=n.kind in ("executive", "final"),
            )
            result = _compile_node_text(
                n.input_text,
                medium_chain=medium_chain,
                heavy_chain=heavy_chain,
                medium_first=medium_first,
                qva_tau=qva_tau,
                deadline_mono=deadline_mono,
                state=state,
                assigned_model=assignment.get("model_id"),
            )
            _apply_result(n, result)
            # If still failing QVA, one heavy-forced recompute of THIS node only.
            # Never replace a durable executive with stitch/failure.
            if (
                not result.get("qva_passed")
                and float(result.get("confidence") or 0) < qva_tau
                and models.is_executive_compile_success(result.get("summary"))
            ):
                n.status = "retrying"
                n.retries += 1
                result2 = _compile_node_text(
                    n.input_text,
                    medium_chain=heavy_chain,
                    heavy_chain=heavy_chain,
                    medium_first=False,
                    qva_tau=qva_tau,
                    deadline_mono=deadline_mono,
                    state=state,
                )
                if models.is_executive_compile_success(result2.get("summary")):
                    _apply_result(n, result2)
                else:
                    n.status = "completed"
                    log.info(
                        "Branch heavy recompute non-durable for %s; keeping prior executive",
                        tid,
                    )
        except Exception as e:
            log.warning("Branch recompute failed for %s: %s", tid, e)
            if models.is_executive_compile_success(n.output_summary):
                n.status = "completed"
            else:
                n.status = "failed"
                n.output_summary = models.stitch_compile_fallback(
                    [n.input_text], reason=f"branch_recompute_{tid}"
                )
                n.status = "completed"
    return touched


def run_dag_compile(
    chunks: Sequence[Any],
    summaries: Sequence[str],
    state: dict,
    *,
    fan_in: int = 8,
    max_depth: int = 12,
    skip_regional_below: int = 0,
    medium_chain: Optional[List[str]] = None,
    heavy_chain: Optional[List[str]] = None,
    medium_first: bool = True,
    qva_tau: float = 0.58,
    max_workers: Optional[int] = None,
    deadline_mono: Optional[float] = None,
    progress_cb: ProgressCb = None,
    existing_nodes: Optional[Dict[str, DagNode]] = None,
    frozen_plan: Any = None,
    pre_executive_ceiling_mono: Optional[float] = None,
    executive_reserved_sec: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Execute hierarchical DAG compile via the shared capacity pool.

    When ``frozen_plan`` is provided, the DAG topology is IMMUTABLE:
    no hierarchy rebuild, no overflow inserts, no dep rewrites.
    """
    from src.core.execution_scheduler import run_capacity_pool

    medium_chain = list(medium_chain or settings.medium_models())
    heavy_chain = list(heavy_chain or settings.heavy_models())
    job_id = str((state or {}).get("job_id") or "")
    unified = bool(getattr(settings, "UNIFIED_DAG_EXECUTOR_ENABLED", True))
    frozen = frozen_plan is not None and bool(getattr(frozen_plan, "frozen", True))
    if unified and not frozen:
        raise RuntimeError(
            "run_dag_compile requires frozen_plan when UNIFIED_DAG_EXECUTOR_ENABLED — "
            "planning must freeze the DAG before execution"
        )
    try:
        from src.perf.critical_path import (
            dag_audit_reset,
            dag_audit_record_node_counts,
            dag_audit_get,
        )

        if job_id:
            dag_audit_reset(job_id)
    except Exception:
        dag_audit_record_node_counts = None  # type: ignore
        dag_audit_get = None  # type: ignore

    if frozen and existing_nodes is not None:
        # Immutable execution: use the planned graph as-is.
        nodes = existing_nodes
        log.info(
            "Job %s: compile executing FROZEN DAG fingerprint=%s nodes=%s",
            job_id,
            getattr(frozen_plan, "fingerprint", "?"),
            len(nodes),
        )
        if job_id and dag_audit_record_node_counts:
            try:
                dag_audit_record_node_counts(
                    job_id,
                    pdag.dag_progress_snapshot(nodes),
                    phase="frozen_exec_start",
                )
            except Exception:
                pass
    else:
        nodes = build_compile_dag(
            chunks,
            summaries,
            fan_in=fan_in,
            max_depth=max_depth,
            skip_regional_below=skip_regional_below,
            existing_nodes=existing_nodes,
        )
        if job_id and dag_audit_record_node_counts:
            try:
                dag_audit_record_node_counts(
                    job_id,
                    pdag.dag_progress_snapshot(nodes),
                    phase="after_build_compile_dag",
                )
            except Exception:
                pass
        # Legacy path only: insert overflow before execution
        for nid, n in list(nodes.items()):
            if n.kind != "chunk" and n.status == "pending":
                pdag.ensure_prompt_budget(nodes, nid)
        if job_id and dag_audit_record_node_counts:
            try:
                dag_audit_record_node_counts(
                    job_id,
                    pdag.dag_progress_snapshot(nodes),
                    phase="after_pre_exec_ensure_prompt_budget",
                )
            except Exception:
                pass

    workers = max(
        1,
        int(
            max_workers
            if max_workers is not None
            else settings.effective_parallel_workers()
        ),
    )
    hard_to = float(getattr(settings, "COMPILE_NODE_HARD_TIMEOUT_SEC", 90.0) or 90.0)
    reserved_sec = float(
        executive_reserved_sec
        if executive_reserved_sec is not None
        else getattr(settings, "COMPILE_RESERVED_SEC", 60.0)
        or 60.0
    )
    abs_deadline = deadline_mono
    pre_ceiling = pre_executive_ceiling_mono
    if pre_ceiling is None and abs_deadline is not None:
        pre_ceiling = float(abs_deadline) - reserved_sec
    t_wall0 = time.perf_counter()
    api_calls = 0
    queue_waits: List[float] = []
    executive_compile_status: Dict[str, Any] = {}

    def _node_deadline(
        n: DagNode, deadline_mono_inner: Optional[float]
    ) -> Optional[float]:
        """
        Budget isolation: executive/final own a fresh reserved wall (exclusive).
        Regional/chapter are clamped to the pre-executive ceiling.
        """
        return phase_deadline_mono(
            n.kind,
            now_mono=time.monotonic(),
            absolute_job_deadline_mono=abs_deadline,
            pre_executive_ceiling_mono=pre_ceiling,
            reserved_sec=reserved_sec,
            per_task_lease_mono=deadline_mono_inner,
        )

    def _ready(n: DagNode) -> bool:
        if n.status not in ("pending", "retrying"):
            return False
        return all(nodes[d].status == "completed" for d in n.dep_ids if d in nodes)

    def _refresh_input(n: DagNode) -> None:
        if not n.dep_ids:
            return
        parts = [
            nodes[d].output_summary
            for d in n.dep_ids
            if d in nodes and nodes[d].output_summary
        ]
        if parts:
            n.input_text = "\n\n".join(parts)
            n.token_estimate = estimate_tokens(n.input_text)

    def _progress(force_msg: Optional[str] = None) -> None:
        if not progress_cb:
            return
        busy = sum(1 for n in nodes.values() if n.status == "running")
        snap = pdag.dag_progress_snapshot(nodes, workers_busy=busy, workers_total=workers)
        # ETA from throughput
        done = snap["completed"]
        elapsed = time.perf_counter() - t_wall0
        rate = done / elapsed if elapsed > 0.5 and done > 0 else 0.0
        eta_sec = (snap["remaining"] / rate) if rate > 0 else None
        snap["eta_sec"] = round(eta_sec, 1) if eta_sec is not None else None
        snap["estimated_finish_epoch"] = (
            round(time.time() + eta_sec, 1) if eta_sec is not None else None
        )
        parts = []
        for k, v in sorted(snap["by_kind"].items()):
            if k == "chunk":
                continue
            label = {
                "regional": "Regional Summaries",
                "chapter": "Chapter Summaries",
                "executive": "Executive Summary",
                "final": "Executive Summary",
            }.get(k, k)
            parts.append(f"{label}: {v['done']}/{v['total']}")
        msg = force_msg or (
            " · ".join(parts) if parts else "Executing frozen DAG…"
        )
        # Audit: surface overflow vs baseline in snapshot (UI may ignore).
        if snap.get("regional_overflow"):
            msg += (
                f" · ovf regional +{snap.get('regional_overflow')}"
                f" (base {snap.get('regional_baseline')})"
            )
        if snap.get("eta_sec") is not None:
            msg += f" · ETA {int(snap['eta_sec'])}s"
        msg += f" · workers {busy}/{workers}"
        pct = 82.0 + 8.0 * (done / max(1, snap["total"]))
        progress_cb(pct, msg, {"dag": snap})
        if job_id and dag_audit_record_node_counts:
            try:
                dag_audit_record_node_counts(job_id, snap, phase="progress")
            except Exception:
                pass

    # Depth-ordered waves; outer pass repeats so mid-run overflow inserts are executed.
    carbon_total = 0.0
    compile_calls = 0
    weak_nodes: List[str] = []

    def _run_payload(payload, deadline_mono_inner: Optional[float] = None):
        nonlocal api_calls, carbon_total, compile_calls, executive_compile_status
        nid = payload if isinstance(payload, str) else payload[0]
        n = nodes[nid]
        # Honor per-node cancel requests (API or timeout reassignment path)
        try:
            job_id = state.get("job_id")
            if job_id:
                from src.db import jobs as job_store

                cancels = set(
                    (job_store.JOB_STATUSES.get(job_id) or {}).get("node_cancels")
                    or []
                )
                if nid in cancels:
                    n.cancel_requested = True
        except Exception:
            pass
        if n.cancel_requested:
            n.status = "failed"
            return nid, None
        node_deadline = _node_deadline(n, deadline_mono_inner)
        # Pre-executive stages stop at the reserved boundary. Executive/final
        # never abort because the absolute job remainder is small — they own
        # the exclusive reserved window.
        if n.kind not in ("executive", "final"):
            if (
                pre_ceiling is not None
                and (float(pre_ceiling) - time.monotonic()) < 2
            ):
                n.status = "failed"
                return nid, None
            if node_deadline is not None and (node_deadline - time.monotonic()) < 5:
                n.status = "failed"
                return nid, None
        n.status = "running"
        n.started_at = time.monotonic()
        try:
            from src.perf.critical_path import dag_audit_record_submit, dag_audit_record_wait

            dep_st = {
                d: (nodes[d].status if d in nodes else "MISSING")
                for d in (n.dep_ids or [])
            }
            # Measure dependency-gate wait (time since last dep finished)
            dep_finish = []
            for d in n.dep_ids or []:
                if d in nodes and nodes[d].finished_at is not None:
                    dep_finish.append(float(nodes[d].finished_at))
            if dep_finish and n.started_at is not None:
                wait_sec = float(n.started_at) - max(dep_finish)
                if wait_sec > 2.0 and job_id:
                    dag_audit_record_wait(
                        job_id,
                        nid=nid,
                        kind=str(n.kind),
                        wait_sec=wait_sec,
                        reason="scheduler_queue_or_worker_capacity_after_deps_ready",
                        unfinished_deps=[],
                    )
            if job_id:
                dag_audit_record_submit(
                    job_id,
                    nid,
                    kind=str(n.kind),
                    deps=list(n.dep_ids or []),
                    dep_statuses=dep_st,
                    attempt=int(getattr(n, "attempts", 0) or 0) + 1,
                )
                # Prove dependency gate: unfinished deps that exist must not happen
                unfinished = [
                    d
                    for d, st in dep_st.items()
                    if st not in ("completed", "MISSING")
                ]
                if unfinished and n.kind in ("executive", "chapter", "regional"):
                    log.warning(
                        "DAG AUDIT: node %s kind=%s marked running with unfinished deps %s",
                        nid,
                        n.kind,
                        unfinished,
                    )
        except Exception:
            pass
        _refresh_input(n)
        if not frozen:
            # Legacy mutable path only
            before_ovf = len(nodes)
            pdag.ensure_prompt_budget(nodes, nid)
            if len(nodes) != before_ovf and job_id and dag_audit_record_node_counts:
                try:
                    dag_audit_record_node_counts(
                        job_id,
                        pdag.dag_progress_snapshot(nodes),
                        phase=f"mid_run_overflow_under_{nid}",
                    )
                except Exception:
                    pass
            if any(
                d in nodes and nodes[d].status != "completed" for d in (n.dep_ids or [])
            ):
                n.status = "pending"
                n.started_at = None
                _progress()
                return nid, {"summary": "", "deferred_overflow": True}
            _refresh_input(n)
        else:
            # Frozen: never insert nodes. Over-budget inputs stitch inside compile.
            if frozen_plan is not None:
                try:
                    from src.core.planning import assert_dag_immutable

                    assert_dag_immutable(nodes, frozen_plan, phase=f"run_{nid}")
                except Exception as e:
                    log.error("Frozen DAG integrity check failed: %s", e)
                    raise
        _progress()
        # Progress stamp attributed to real node kind (regional/chapter/executive).
        try:
            state["_compile_audit_kind"] = n.kind
            state["_compile_audit_nid"] = nid
        except Exception:
            pass
        assignment = assign_model_for_node(
            node_kind=n.kind,
            min_tier="medium",
            model_chain=medium_chain,
            state=state,
            prefer_quality=n.kind in ("executive", "final"),
        )
        n.assigned_model = assignment.get("model_id")
        try:
            from src.core.pipeline_executor import _run_with_hard_isolation

            def _invoke_compile():
                return _compile_node_text(
                    n.input_text,
                    medium_chain=medium_chain,
                    heavy_chain=heavy_chain,
                    medium_first=medium_first,
                    qva_tau=qva_tau,
                    deadline_mono=node_deadline,
                    state=state,
                    assigned_model=n.assigned_model,
                )

            node_hard = reserved_sec if n.kind in ("executive", "final") else hard_to
            if node_deadline is not None:
                node_hard = min(
                    node_hard, max(1.0, float(node_deadline) - time.monotonic())
                )
            result = _run_with_hard_isolation(
                _invoke_compile,
                hard_timeout_sec=node_hard,
                label=nid,
            )
            api_calls += 1
            try:
                from src.core.node_assigner import record_model_latency

                record_model_latency(
                    n.assigned_model or (medium_chain[0] if medium_chain else None),
                    float(result.get("latency_ms") or 0),
                )
            except Exception:
                pass
            _apply_result(n, result, worker_id=f"w-{nid}")
            if n.kind in ("executive", "final") and isinstance(
                result.get("compile_status"), dict
            ):
                executive_compile_status = dict(result["compile_status"])
            carbon_total += n.carbon_estimate_g
            compile_calls += 1 if n.status == "completed" else 0
            if n.status == "completed" and (
                not result.get("qva_passed")
                or float(result.get("confidence") or 0) < qva_tau
            ):
                # Only queue repair when we lack a durable executive (monotonic).
                if not models.is_executive_compile_success(result.get("summary")):
                    weak_nodes.append(nid)
                elif n.kind not in ("executive", "final"):
                    weak_nodes.append(nid)
            _progress()
            return nid, result
        except Exception as e:
            log.warning("DAG node %s failed: %s", nid, e)
            # Keep any durable summary already on the node (monotonic).
            if models.is_executive_compile_success(n.output_summary):
                n.status = "completed"
                n.finished_at = time.monotonic()
                _progress()
                return nid, {"summary": n.output_summary, "kept_prior": True}
            n.retries += 1
            n.status = "retrying"
            _progress()
            # Node-level fallback: next models / heavy, without stalling siblings
            retry_deadline = _node_deadline(n, deadline_mono_inner)
            if n.retries < 2 and (
                retry_deadline is None or (retry_deadline - time.monotonic()) > 20
            ):
                try:
                    from src.core.pipeline_executor import _run_with_hard_isolation

                    def _invoke_retry():
                        return _compile_node_text(
                            n.input_text,
                            medium_chain=heavy_chain,
                            heavy_chain=heavy_chain,
                            medium_first=False,
                            qva_tau=qva_tau,
                            deadline_mono=retry_deadline,
                            state=state,
                        )

                    retry_hard = (
                        reserved_sec if n.kind in ("executive", "final") else hard_to
                    )
                    if retry_deadline is not None:
                        retry_hard = min(
                            retry_hard,
                            max(1.0, float(retry_deadline) - time.monotonic()),
                        )
                    result = _run_with_hard_isolation(
                        _invoke_retry,
                        hard_timeout_sec=retry_hard,
                        label=f"{nid}-retry",
                    )
                    api_calls += 1
                    if models.is_executive_compile_success(result.get("summary")):
                        _apply_result(n, result)
                        if n.kind in ("executive", "final") and isinstance(
                            result.get("compile_status"), dict
                        ):
                            executive_compile_status = dict(result["compile_status"])
                        carbon_total += n.carbon_estimate_g
                        compile_calls += 1
                        _progress()
                        return nid, result
                    log.info(
                        "DAG node %s retry non-durable; not adopting over empty prior",
                        nid,
                    )
                except Exception as e2:
                    log.error("DAG node %s reassign/retry failed: %s", nid, e2)
            n.status = "failed"
            _progress()
            return nid, None

    def _is_ok(res) -> bool:
        if res is None:
            return False
        try:
            _nid, result = res
        except Exception:
            return False
        if result is None:
            return False
        if result.get("deferred_overflow"):
            return True  # not a failure — parent will run after overflow children
        return bool((result.get("summary") or "").strip())

    def _on_progress(prog, mets) -> None:
        _progress()

    for _wave_pass in range(64):
        max_d = max((n.depth for n in nodes.values()), default=0)
        ran_any = False
        for depth in range(0, max_d + 1):
            wave = [
                n
                for n in nodes.values()
                if n.depth == depth and n.kind != "chunk" and _ready(n)
            ]
            if not wave:
                continue
            ran_any = True
            wave.sort(key=lambda n: priority_for_kind(n.kind))

            payloads = [n.id for n in wave]

            def _worker(p, deadline_mono=None):
                return _run_payload(p, deadline_mono)

            wave_is_exec = any(n.kind in ("executive", "final") for n in wave)
            pool_hard = reserved_sec if wave_is_exec else hard_to
            # Executive waves: no absolute-job ceiling — hard_timeout alone
            # grants the exclusive reserved lease. Pre-exec waves stay clamped.
            pool_ceiling = None if wave_is_exec else pre_ceiling
            ordered, prog, mets = run_capacity_pool(
                payloads,
                _worker,
                role="compile",
                kind="compile",
                max_workers=workers,
                hard_timeout_sec=pool_hard,
                max_attempts=2,
                is_success=_is_ok,
                on_progress=_on_progress,
                deadline_ceiling_mono=pool_ceiling,
            )
            if mets:
                queue_waits.append(float(mets.to_dict().get("avg_queue_wait_ms") or 0.0))

            # Failed nodes: stitch so parents can proceed (non-blocking).
            # Never overwrite a durable executive compile with stitch.
            for n in wave:
                if n.status == "pending":
                    continue
                if models.is_executive_compile_success(n.output_summary):
                    n.status = "completed"
                    continue
                if n.status != "completed" or not (n.output_summary or "").strip():
                    n.output_summary = models.stitch_compile_fallback(
                        [n.input_text], reason=f"dag_node_{n.id}_failed"
                    )
                    n.status = "completed"

        if not ran_any:
            break

    # Anything still pending after wave passes: stitch so the pipeline can finish.
    for n in nodes.values():
        if n.kind == "chunk":
            continue
        if models.is_executive_compile_success(n.output_summary):
            n.status = "completed"
            continue
        if n.status in ("pending", "retrying", "running", "failed") and not (
            n.output_summary or ""
        ).strip():
            n.output_summary = models.stitch_compile_fallback(
                [n.input_text], reason=f"dag_node_{n.id}_unresolved"
            )
            n.status = "completed"

    # Repair queue: re-run weak nodes WITHOUT mutating DAG topology
    branch_recompiles: List[Dict[str, Any]] = []
    repair_report: Dict[str, Any] = {}
    try:
        from src.core.repair_queue import RepairQueue, run_repair_tasks

        rq = RepairQueue(job_id or "anon")
        for wid in weak_nodes[:3]:
            if wid in nodes:
                rq.enqueue(wid, reason="weak_qva", priority=10)

        def _repair_one(nid: str) -> bool:
            if frozen_plan is not None:
                from src.core.planning import assert_dag_immutable

                assert_dag_immutable(nodes, frozen_plan, phase=f"repair_{nid}")
            before = len(nodes)
            touched = recompute_branch(
                nodes,
                nid,
                state=state,
                medium_chain=medium_chain,
                heavy_chain=heavy_chain,
                medium_first=medium_first,
                qva_tau=qva_tau,
                deadline_mono=deadline_mono,
            )
            if len(nodes) != before:
                raise RuntimeError(
                    f"Repair mutated DAG node count {before} → {len(nodes)}"
                )
            branch_recompiles.append({"node": nid, "touched": touched})
            return bool(touched)

        repair_report = run_repair_tasks(rq, recompute_fn=_repair_one, max_tasks=3)
        api_calls += int(repair_report.get("completed") or 0)
    except Exception as e:
        log.warning("Repair queue failed (non-fatal): %s", e)
        repair_report = {"error": str(e)}

    # Final output
    final_nodes = [
        n
        for n in nodes.values()
        if n.kind in ("executive", "final") and n.status == "completed"
    ]
    if not final_nodes:
        depth_max = max((n.depth for n in nodes.values()), default=0)
        final_nodes = [
            n
            for n in nodes.values()
            if n.depth == depth_max and n.kind != "chunk" and n.status == "completed"
        ]
    used_stitched_fallback = False
    # Prefer any durable executive already on final nodes (monotonic).
    durable_finals = [
        n
        for n in final_nodes
        if models.is_executive_compile_success(n.output_summary)
    ]
    if len(durable_finals) == 1:
        final_summary = durable_finals[0].output_summary
        if not executive_compile_status:
            executive_compile_status = {
                "compile_status": "ok",
                "summary_source": "executive_compile",
                "best_compile_model": durable_finals[0].assigned_model,
            }
    elif len(final_nodes) == 1:
        final_summary = final_nodes[0].output_summary
        if models.is_stitched_fallback(final_summary):
            used_stitched_fallback = True
            executive_compile_status = {
                "compile_status": "stitched_fallback",
                "summary_source": "stitched_fallback",
                "best_compile_model": None,
            }
    elif durable_finals:
        # Multiple durable executives: merge only if merge yields durable text;
        # otherwise keep the longest durable executive (never stitch over them).
        joined = "\n\n".join(n.output_summary for n in durable_finals)
        # Exclusive reserved wall — never min(remaining_job, reserved).
        merge_deadline = time.monotonic() + reserved_sec
        try:
            merged = models.run_compile_with_models(
                [joined],
                state,
                heavy_chain if any(n.used_heavy for n in durable_finals) else medium_chain,
                deadline_mono=merge_deadline,
            )
            compile_calls += 1
            api_calls += 1
            if models.is_executive_compile_success(merged):
                final_summary = merged
            else:
                final_summary = max(
                    (n.output_summary for n in durable_finals),
                    key=lambda s: len(str(s or "")),
                )
                log.info("Final merge non-durable; keeping best durable executive")
        except Exception:
            final_summary = max(
                (n.output_summary for n in durable_finals),
                key=lambda s: len(str(s or "")),
            )
    elif final_nodes:
        final_summary = models.stitch_compile_fallback(
            [n.output_summary for n in final_nodes], reason="final_merge_failed"
        )
        used_stitched_fallback = True
    else:
        # Chunk-only DAG should be rare after hierarchy always wraps an executive.
        usable = [str(s).strip() for s in (summaries or []) if str(s or "").strip()]
        exec_deadline = time.monotonic() + reserved_sec
        if usable and (exec_deadline - time.monotonic()) > 8.0:
            try:
                recovered = models.run_compile_with_models(
                    usable,
                    state,
                    heavy_chain or medium_chain,
                    deadline_mono=exec_deadline,
                )
                compile_calls += 1
                api_calls += 1
                if models.is_executive_compile_success(recovered):
                    final_summary = recovered
                    log.info(
                        "Recovered executive summary via direct compile after empty DAG finals"
                    )
                else:
                    final_summary = models.stitch_compile_fallback(
                        usable, reason="no_executive_node"
                    )
                    used_stitched_fallback = True
            except Exception as e:
                log.warning("Direct compile after dag_empty failed: %s", e)
                final_summary = models.stitch_compile_fallback(
                    usable, reason="no_executive_node"
                )
                used_stitched_fallback = True
        else:
            final_summary = models.stitch_compile_fallback(
                list(summaries), reason="no_executive_node"
            )
            used_stitched_fallback = True

    # Never surface stitch when a durable executive exists anywhere in finals.
    if models.is_executive_compile_success(final_summary):
        used_stitched_fallback = False
        if executive_compile_status.get("summary_source") != "executive_compile":
            executive_compile_status.setdefault("summary_source", "executive_compile")
            executive_compile_status.setdefault("compile_status", "ok")
    elif models.is_stitched_fallback(final_summary):
        used_stitched_fallback = True

    _progress("DAG compile complete")
    wall_ms = (time.perf_counter() - t_wall0) * 1000.0
    avg_qwait = sum(queue_waits) / len(queue_waits) if queue_waits else 0.0
    seq_baseline = sum(float(n.latency_ms or 0.0) for n in nodes.values() if n.kind != "chunk")
    try:
        metrics = pdag.perf_metrics(
            nodes,
            wall_ms=wall_ms,
            workers=workers,
            queue_wait_ms_avg=avg_qwait,
            api_calls=api_calls,
            sequential_baseline_ms=seq_baseline if seq_baseline > 0 else wall_ms,
        )
    except Exception as e:
        log.warning("perf_metrics failed (non-fatal): %s", e)
        metrics = {
            "execution_time_ms": round(wall_ms, 1),
            "api_calls": api_calls,
            "workers": workers,
            "critical_path_ms": 0.0,
        }
    rollups = pdag.carbon_rollups(nodes)

    # Hierarchy UI from frozen topology — never rebuild (would diverge from overflow).
    if frozen and frozen_plan is not None:
        levels_ui = hierarchy_mod.hierarchy_tree_from_frozen_nodes(
            nodes,
            overflow_ids=list(getattr(frozen_plan, "overflow_ids", None) or []),
        )
        if getattr(frozen_plan, "compression", None):
            levels_ui["compression"] = dict(frozen_plan.compression)
    else:
        levels_ui = hierarchy_mod.hierarchy_tree_for_ui(
            hierarchy_mod.build_hierarchy_levels(
                chunks,
                summaries,
                fan_in=fan_in,
                max_depth=max_depth,
                skip_regional_below=skip_regional_below,
            )
        )
    node_status = {nid: n.to_dict() for nid, n in nodes.items()}

    # Fingerprint after execution (must match plan)
    fingerprint_after = None
    if frozen and frozen_plan is not None:
        try:
            from src.core.planning import fingerprint_topology, assert_dag_immutable, update_planner_ema

            fingerprint_after = fingerprint_topology(nodes)
            assert_dag_immutable(nodes, frozen_plan, phase="compile_complete")
            compile_n = sum(1 for x in nodes.values() if x.kind != "chunk")
            wall_s = wall_ms / 1000.0
            update_planner_ema(
                {
                    "runtime_sec": wall_s,
                    "carbon_g": carbon_total,
                    "api_calls": compile_calls,
                    "hierarchy_depth": max((n.depth for n in nodes.values()), default=0),
                    "sec_per_compile_node": (wall_s / max(1, compile_n)) * max(1, workers),
                    "carbon_per_compile_node": carbon_total / max(1, compile_n),
                }
            )
        except Exception as e:
            log.error("Post-compile fingerprint/EMA failed: %s", e)
            raise

    audit_payload: Dict[str, Any] = {}
    try:
        from src.perf.critical_path import dag_audit_get, dag_audit_record_node_counts

        if job_id:
            dag_audit_record_node_counts(
                job_id,
                pdag.dag_progress_snapshot(nodes),
                phase="compile_complete",
            )
            audit_payload = dict(dag_audit_get(job_id) or {})
            # Compact for return (drop huge ready_events tails in payload)
            if len(audit_payload.get("ready_events") or []) > 100:
                audit_payload["ready_events"] = audit_payload["ready_events"][-100:]
            multi_submits = {
                k: v
                for k, v in (audit_payload.get("submit_counts") or {}).items()
                if int(v) > 1
            }
            if multi_submits:
                log.info(
                    "Job %s: [DAG AUDIT] nodes submitted >1 time: %s",
                    job_id,
                    multi_submits,
                )
            log.info(
                "Job %s: [DAG AUDIT] overflow_inserts=%s deferred=%s "
                "misleading_executive_msgs=%s",
                job_id,
                len(audit_payload.get("overflow_inserts") or []),
                len(audit_payload.get("deferred_overflow") or []),
                audit_payload.get("misleading_executive_msgs"),
            )
    except Exception as e:
        log.debug("dag audit finalize skip: %s", e)

    status_out = dict(executive_compile_status or {})
    if used_stitched_fallback and not models.is_executive_compile_success(final_summary):
        status_out.setdefault("compile_status", "stitched_fallback")
        status_out.setdefault("summary_source", "stitched_fallback")
    elif models.is_executive_compile_success(final_summary):
        status_out.setdefault("compile_status", status_out.get("compile_status") or "ok")
        status_out.setdefault("summary_source", "executive_compile")

    return {
        "final_summary": models.strip_outer_markdown_fence(final_summary),
        "compile_calls": compile_calls,
        "compile_carbon_g": round(carbon_total, 4),
        "used_heavy": any(n.used_heavy for n in nodes.values()),
        "used_stitched_fallback": used_stitched_fallback,
        "compile_status": status_out.get("compile_status"),
        "compile_attempts": status_out.get("compile_attempts") or [],
        "best_compile_model": status_out.get("best_compile_model"),
        "heavy_compile_skipped": status_out.get("heavy_compile_skipped"),
        "summary_source": status_out.get("summary_source"),
        "executive_reserved_sec": reserved_sec,
        "hierarchy": levels_ui,
        "dag_nodes": node_status,
        "workers": workers,
        "endpoint_pool": _safe_pool_snapshot(),
        "carbon_rollups": rollups,
        "perf_metrics": metrics,
        "branch_recompiles": branch_recompiles,
        "repair_report": repair_report,
        "frozen": frozen,
        "fingerprint_after": fingerprint_after,
        "engine": "dag",
        "nodes": nodes,
        "dag_audit": audit_payload,
    }
