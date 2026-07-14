"""
Hierarchical DAG compile engine.

Turns hierarchy levels into independently executable nodes. Within a level,
all ready nodes run in parallel via a worker pool + priority queue. Each merge
node uses medium-first compile with per-node QVA; heavy only on failure.

Does not replace map_summarize — L0 chunk nodes are already complete.
"""
from __future__ import annotations

import concurrent.futures
import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional, Sequence

from src.agents import models, quality_validation
from src.chunking.service import estimate_tokens
from src.core import hierarchy as hierarchy_mod
from src.core.config import settings
from src.core.priority_queue import priority_for_kind

log = logging.getLogger(__name__)

ProgressCb = Optional[Callable[[float, str, Dict[str, Any]], None]]


@dataclass
class DagNode:
    id: str
    kind: str
    depth: int
    dep_ids: List[str] = field(default_factory=list)
    status: str = "pending"  # pending|ready|running|completed|failed|retrying
    assigned_model: Optional[str] = None
    endpoint_id: Optional[str] = None
    carbon_estimate_g: float = 0.0
    latency_ms: float = 0.0
    retries: int = 0
    input_text: str = ""
    output_summary: str = ""
    section_path: str = ""
    token_estimate: int = 0
    qva_confidence: float = 0.0
    used_heavy: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _context_token_budget() -> int:
    """Keep compile prompts under ~80% of a conservative context window."""
    window = int(getattr(settings, "COMPILE_CONTEXT_WINDOW_TOKENS", 12000) or 12000)
    frac = float(getattr(settings, "COMPILE_PROMPT_MAX_CONTEXT_FRAC", 0.80) or 0.80)
    soft = int(getattr(settings, "COMPILE_MAX_INPUT_TOKENS", 10000) or 10000)
    return max(1000, min(soft, int(window * frac)))


def build_compile_dag(
    chunks: Sequence[Any],
    summaries: Sequence[str],
    *,
    fan_in: int = 8,
    max_depth: int = 12,
    skip_regional_below: int = 0,
) -> Dict[str, DagNode]:
    """
    Build DAG from hierarchy levels.
    L0 chunk nodes are pre-completed. Higher levels depend on lower node ids.
    """
    levels = hierarchy_mod.build_hierarchy_levels(
        chunks,
        summaries,
        fan_in=fan_in,
        max_depth=max_depth,
        skip_regional_below=skip_regional_below,
    )
    nodes: Dict[str, DagNode] = {}
    level_ids: List[List[str]] = []
    # source_indices (chunk idx) → chunk node id
    chunk_id_by_idx: Dict[int, str] = {}

    for lv in levels:
        level_num = int(lv.get("level") or 0)
        kind = str(lv.get("kind") or "compile")
        ids_this: List[str] = []
        for n in list(lv.get("nodes") or []):
            nid = str(n.get("id"))
            text = str(n.get("text") or "")
            src = [int(x) for x in (n.get("source_indices") or [])]
            if level_num == 0:
                for idx in src:
                    chunk_id_by_idx[idx] = nid
                node = DagNode(
                    id=nid,
                    kind="chunk",
                    depth=0,
                    dep_ids=[],
                    status="completed",
                    output_summary=text,
                    input_text=text,
                    section_path=str(n.get("section_path") or ""),
                    token_estimate=int(n.get("token_estimate") or estimate_tokens(text)),
                )
            else:
                k = kind
                if k == "compile":
                    k = "executive" if level_num >= 3 else "chapter"
                node = DagNode(
                    id=nid,
                    kind=k,
                    depth=level_num,
                    dep_ids=[],
                    status="pending",
                    input_text=text,
                    section_path=str(n.get("section_path") or ""),
                    token_estimate=int(n.get("token_estimate") or estimate_tokens(text)),
                )
            nodes[nid] = node
            ids_this.append(nid)
        level_ids.append(ids_this)

    pack_fan = max(2, int(fan_in or 8))
    for li, lv in enumerate(levels):
        if li == 0:
            continue
        kind = str(lv.get("kind") or "")
        cur = level_ids[li]
        prev = level_ids[li - 1]
        raw_nodes = list(lv.get("nodes") or [])
        for ci, cid in enumerate(cur):
            deps: List[str] = []
            if kind == "regional" or (
                li == 1 and kind != "chapter"
            ):
                # Regional: depend on chunk nodes via source_indices
                src = [int(x) for x in (raw_nodes[ci].get("source_indices") or [])]
                deps = [
                    chunk_id_by_idx[i]
                    for i in src
                    if i in chunk_id_by_idx
                ]
            else:
                start = ci * pack_fan
                end = min(len(prev), start + pack_fan)
                deps = prev[start:end]
            if not deps and prev:
                deps = [prev[min(ci, len(prev) - 1)]]
            nodes[cid].dep_ids = list(deps)
            parts = [
                nodes[d].output_summary or nodes[d].input_text
                for d in deps
                if d in nodes
            ]
            if parts:
                nodes[cid].input_text = "\n\n".join(parts)
                nodes[cid].token_estimate = estimate_tokens(nodes[cid].input_text)

    # If the top level has multiple nodes, add a final executive node
    if level_ids:
        top = level_ids[-1]
        if len(top) > 1:
            fid = "final-executive"
            parts = [nodes[i].input_text for i in top]
            nodes[fid] = DagNode(
                id=fid,
                kind="executive",
                depth=len(level_ids),
                dep_ids=list(top),
                status="pending",
                input_text="\n\n".join(parts),
                section_path="executive",
                token_estimate=estimate_tokens("\n\n".join(parts)),
            )
        elif len(top) == 1 and nodes[top[0]].kind != "chunk":
            nodes[top[0]].kind = "executive"

    return nodes


def _split_oversized_input(text: str, budget: int) -> List[str]:
    """If a single prompt is too large, split into sub-batches under budget."""
    toks = estimate_tokens(text)
    if toks <= budget:
        return [text]
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    if len(paras) <= 1:
        # Hard character split
        approx_chars = max(500, budget * 4)
        return [text[i : i + approx_chars] for i in range(0, len(text), approx_chars)]
    batches: List[str] = []
    cur: List[str] = []
    cur_tok = 0
    for p in paras:
        pt = estimate_tokens(p)
        if cur and cur_tok + pt > budget:
            batches.append("\n\n".join(cur))
            cur, cur_tok = [], 0
        cur.append(p)
        cur_tok += pt
    if cur:
        batches.append("\n\n".join(cur))
    return batches or [text]


def _compile_node_text(
    text: str,
    *,
    medium_chain: List[str],
    heavy_chain: List[str],
    medium_first: bool,
    qva_tau: float,
    deadline_mono: Optional[float],
    state: dict,
) -> Dict[str, Any]:
    """Medium-first compile + optional heavy for one node."""
    budget = _context_token_budget()
    parts = _split_oversized_input(text, budget)
    # If split, compile parts then merge
    partials: List[str] = []
    used_heavy = False
    model_used = None
    carbon = 0.0
    t0 = time.perf_counter()

    def _one(prompt: str, chain: List[str]) -> str:
        nonlocal model_used, carbon
        out = models.run_compile_with_models(
            [prompt],
            state,
            chain,
            deadline_mono=deadline_mono,
        )
        carbon += 0.25 if chain == medium_chain else 0.41
        return out

    for part in parts:
        chain = medium_chain if medium_first else heavy_chain
        summary = _one(part, chain)
        verdict = quality_validation.validate_final([part], summary)
        if (not verdict.passed or float(verdict.confidence) < qva_tau) and medium_first:
            if deadline_mono is None or (deadline_mono - time.monotonic()) > 15:
                summary = _one(part, heavy_chain)
                used_heavy = True
                verdict = quality_validation.validate_final([part], summary)
        partials.append(summary)
        model_used = (state.get("models_used") or [None])[-1] if state.get("models_used") else model_used

    if len(partials) == 1:
        final = partials[0]
        conf = quality_validation.validate_final([text], final).confidence
    else:
        merged_in = "\n\n".join(partials)
        final = _one(merged_in, heavy_chain if used_heavy else medium_chain)
        conf = quality_validation.validate_final(partials, final).confidence

    return {
        "summary": models.strip_outer_markdown_fence(final),
        "used_heavy": used_heavy,
        "confidence": float(conf),
        "carbon_g": carbon,
        "latency_ms": (time.perf_counter() - t0) * 1000.0,
        "model": model_used,
    }


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
) -> Dict[str, Any]:
    """
    Execute hierarchical DAG compile. Returns final_summary + dag metadata.
    """
    medium_chain = list(medium_chain or settings.medium_models())
    heavy_chain = list(heavy_chain or settings.heavy_models())
    nodes = build_compile_dag(
        chunks,
        summaries,
        fan_in=fan_in,
        max_depth=max_depth,
        skip_regional_below=skip_regional_below,
    )
    workers = max(
        1,
        int(
            max_workers
            if max_workers is not None
            else getattr(settings, "COMPILE_MAX_WORKERS", 4)
            or 4
        ),
    )

    def _ready(n: DagNode) -> bool:
        if n.status != "pending":
            return False
        return all(
            nodes[d].status == "completed"
            for d in n.dep_ids
            if d in nodes
        )

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
        by_kind: Dict[str, Dict[str, int]] = {}
        done = run = fail = pending = 0
        for n in nodes.values():
            if n.kind == "chunk":
                continue
            bucket = by_kind.setdefault(n.kind, {"done": 0, "total": 0, "running": 0})
            bucket["total"] += 1
            if n.status == "completed":
                bucket["done"] += 1
                done += 1
            elif n.status == "running":
                bucket["running"] += 1
                run += 1
            elif n.status == "failed":
                fail += 1
            else:
                pending += 1
        total = max(1, done + run + fail + pending)
        pct = 82.0 + 8.0 * (done / total)
        parts = [
            f"{k}: {v['done']}/{v['total']}"
            for k, v in sorted(by_kind.items())
        ]
        msg = force_msg or (
            "DAG compile — " + ", ".join(parts) if parts else "DAG compile..."
        )
        progress_cb(
            pct,
            msg,
            {
                "dag": {
                    "by_kind": by_kind,
                    "workers": workers,
                    "completed": done,
                    "running": run,
                    "failed": fail,
                    "pending": pending,
                }
            },
        )

    # Depth-ordered waves (dependencies always point to lower depth)
    max_d = max((n.depth for n in nodes.values()), default=0)
    carbon_total = 0.0
    compile_calls = 0

    for depth in range(0, max_d + 1):
        wave = [
            n
            for n in nodes.values()
            if n.depth == depth and n.kind != "chunk" and n.status == "pending"
        ]
        # Only those whose deps are satisfied
        wave = [n for n in wave if _ready(n)]
        if not wave:
            continue
        # Priority: executive first within wave
        wave.sort(key=lambda n: priority_for_kind(n.kind))

        def _run(nid: str) -> None:
            nonlocal carbon_total, compile_calls
            n = nodes[nid]
            if deadline_mono is not None and (deadline_mono - time.monotonic()) < 5:
                n.status = "failed"
                n.output_summary = ""
                return
            n.status = "running"
            _refresh_input(n)
            _progress()
            try:
                result = _compile_node_text(
                    n.input_text,
                    medium_chain=medium_chain,
                    heavy_chain=heavy_chain,
                    medium_first=medium_first,
                    qva_tau=qva_tau,
                    deadline_mono=deadline_mono,
                    state=state,
                )
                n.output_summary = result["summary"]
                n.used_heavy = bool(result["used_heavy"])
                n.qva_confidence = float(result["confidence"])
                n.carbon_estimate_g = float(result["carbon_g"])
                n.latency_ms = float(result["latency_ms"])
                n.assigned_model = result.get("model")
                n.status = "completed" if n.output_summary.strip() else "failed"
                carbon_total += n.carbon_estimate_g
                compile_calls += 1 if n.status == "completed" else 0
            except Exception as e:
                log.warning("DAG node %s failed: %s", nid, e)
                n.retries += 1
                if n.retries < 2 and (
                    deadline_mono is None or (deadline_mono - time.monotonic()) > 20
                ):
                    n.status = "retrying"
                    try:
                        result = _compile_node_text(
                            n.input_text,
                            medium_chain=heavy_chain,
                            heavy_chain=heavy_chain,
                            medium_first=False,
                            qva_tau=qva_tau,
                            deadline_mono=deadline_mono,
                            state=state,
                        )
                        n.output_summary = result["summary"]
                        n.used_heavy = True
                        n.qva_confidence = float(result["confidence"])
                        n.carbon_estimate_g = float(result["carbon_g"])
                        n.latency_ms = float(result["latency_ms"])
                        n.status = (
                            "completed" if n.output_summary.strip() else "failed"
                        )
                        carbon_total += n.carbon_estimate_g
                        compile_calls += 1
                    except Exception as e2:
                        log.error("DAG node %s retry failed: %s", nid, e2)
                        n.status = "failed"
                else:
                    n.status = "failed"
            _progress()

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(_run, n.id) for n in wave]
            for fut in concurrent.futures.as_completed(futs):
                try:
                    fut.result()
                except Exception as e:
                    log.error("DAG worker error: %s", e)

        # Failed nodes in this wave: stitch from input so parents can proceed
        for n in wave:
            if n.status != "completed" or not n.output_summary.strip():
                n.output_summary = models.stitch_compile_fallback(
                    [n.input_text], reason=f"dag_node_{n.id}_failed"
                )
                n.status = "completed"

    # Pick final output: executive/final node, else highest depth completed
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
    if len(final_nodes) == 1:
        final_summary = final_nodes[0].output_summary
    elif final_nodes:
        # Last-resort merge of top nodes
        joined = "\n\n".join(n.output_summary for n in final_nodes)
        try:
            final_summary = models.run_compile_with_models(
                [joined],
                state,
                heavy_chain if any(n.used_heavy for n in final_nodes) else medium_chain,
                deadline_mono=deadline_mono,
            )
            compile_calls += 1
        except Exception:
            final_summary = models.stitch_compile_fallback(
                [n.output_summary for n in final_nodes], reason="final_merge_failed"
            )
    else:
        final_summary = models.stitch_compile_fallback(
            list(summaries), reason="dag_empty"
        )

    _progress("DAG compile complete")

    # UI tree enriched with statuses
    levels_ui = hierarchy_mod.hierarchy_tree_for_ui(
        hierarchy_mod.build_hierarchy_levels(
            chunks,
            summaries,
            fan_in=fan_in,
            max_depth=max_depth,
            skip_regional_below=skip_regional_below,
        )
    )
    node_status = {nid: n.to_dict() for nid, n in nodes.items() if n.kind != "chunk"}

    return {
        "final_summary": models.strip_outer_markdown_fence(final_summary),
        "compile_calls": compile_calls,
        "compile_carbon_g": round(carbon_total, 4),
        "used_heavy": any(n.used_heavy for n in nodes.values()),
        "hierarchy": levels_ui,
        "dag_nodes": node_status,
        "workers": workers,
        "endpoint_pool": _safe_pool_snapshot(),
    }


def _safe_pool_snapshot() -> List[Dict[str, Any]]:
    try:
        from src.agents import nim_endpoint_pool as pool

        return pool.pool_snapshot()
    except Exception:
        return []
