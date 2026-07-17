"""
System benchmark adapter — Intelligent Router as a first-class participant.

Invokes production routing resolution + NIM generation **in-process**
(no HTTP). Uses the same frozen system/user/context messages as GPT runners.
Does not modify production APIs, ResponseAgent skills, or carbon accounting logic.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from src.eval.gpt_benchmark.openai_client import (
    ModelRunResult,
    _attach_energy,
    _estimate_tokens_fallback,
    _tokens_per_sec,
)
from src.eval.gpt_benchmark.participants import (
    INTELLIGENT_ROUTER_DISPLAY,
    INTELLIGENT_ROUTER_ID,
)
from src.eval.gpt_benchmark.pricing import estimate_api_cost_usd, energy_tier_for_model


def load_routing_decision(document_id: str) -> Optional[Dict[str, Any]]:
    """Read persisted RoutingDecision for a document (query-path source of truth)."""
    if not document_id:
        return None
    try:
        from src.memory import storage

        return storage.get_routing_decision(document_id)
    except Exception:
        return None


def _routing_metadata(
    *,
    routing_decision: Optional[Dict[str, Any]],
    model_ids: List[str],
    tier: str,
    model_used: Optional[str],
    call_meta: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    rd = routing_decision or {}
    return {
        "participant": INTELLIGENT_ROUTER_ID,
        "display_name": INTELLIGENT_ROUTER_DISPLAY,
        "execution_path": "in_process_nim_via_routing_decision",
        "http_bypassed": True,
        "selected_model": rd.get("selected_model"),
        "model_used": model_used,
        "model_chain": list(model_ids),
        "tier": tier,
        "compile_tier": rd.get("compile_tier"),
        "mode": rd.get("mode"),
        "fallbacks": rd.get("fallbacks") or [],
        "compile_fallbacks": rd.get("compile_fallbacks") or [],
        "reason_summary": rd.get("reason_summary"),
        "policy_version": rd.get("policy_version"),
        "utility": rd.get("utility"),
        "crs": rd.get("crs"),
        "document_type": rd.get("document_type"),
        "signals": rd.get("signals"),
        "routing_decision_present": bool(routing_decision),
        "call_meta": {
            k: call_meta.get(k)
            for k in (
                "chain_slices",
                "chain_slice_plan",
                "endpoint_role",
                "models_attempted",
                "fallback_used",
            )
            if call_meta and k in call_meta
        }
        if call_meta
        else {},
    }


def run_intelligent_router(
    *,
    document_id: str,
    question: str,
    messages: List[Dict[str, str]],
    context_tokens: int,
    retrieval_hits: int,
    max_tokens: int = 500,
    temperature: float = 0.2,
    input_verification: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
    routing_decision: Optional[Dict[str, Any]] = None,
) -> ModelRunResult:
    """
    Execute the Intelligent Router participant on frozen benchmark messages.

    Steps (no production HTTP):
      1. Load / accept RoutingDecision
      2. resolve_model_chain (production helper, read-only)
      3. call_chat_with_fallback with the **frozen** messages
      4. Map timings/tokens/cost/carbon into ModelRunResult
    """
    from src.agents import models as models_mod
    from src.agents.response_agent import resolve_model_chain

    result = ModelRunResult(
        model=INTELLIGENT_ROUTER_ID,
        ok=False,
        model_requested=INTELLIGENT_ROUTER_ID,
        participant_kind="system_router",
    )
    result.input_verification = dict(input_verification or {})

    rd = routing_decision if routing_decision is not None else load_routing_decision(
        document_id
    )
    model_ids, tier = resolve_model_chain(rd)

    if dry_run:
        prompt_blob = "\n".join(m.get("content") or "" for m in messages)
        est_prompt = _estimate_tokens_fallback(prompt_blob)
        selected = (rd or {}).get("selected_model") or (
            model_ids[0] if model_ids else None
        )
        est_cost = estimate_api_cost_usd(selected or "", est_prompt, max_tokens)
        result.ok = True
        result.dry_run = True
        result.model_returned = selected
        result.prompt_tokens = est_prompt
        result.completion_tokens = 0
        result.total_tokens = est_prompt
        result.latency_ms = 0.0
        result.ttft_ms = None
        result.estimated_api_cost_usd = 0.0
        result.provider_metadata = {
            "dry_run": True,
            "estimated_api_cost_usd_upper_bound": round(est_cost, 8),
            "note": (
                "Dry-run: no NIM call. Cost upper-bound assumes full "
                f"max_tokens={max_tokens} on selected/fallback model."
            ),
        }
        result.routing = _routing_metadata(
            routing_decision=rd,
            model_ids=model_ids,
            tier=tier,
            model_used=selected,
            call_meta=None,
        )
        return result

    if models_mod.get_nim_client() is None:
        result.error = (
            "NVIDIA_API_KEY / NIM client is required for the Intelligent Router "
            "participant (in-process generation)."
        )
        result.routing = _routing_metadata(
            routing_decision=rd,
            model_ids=model_ids,
            tier=tier,
            model_used=None,
            call_meta=None,
        )
        return result

    if not model_ids:
        result.error = "Routing resolved an empty model chain."
        result.routing = _routing_metadata(
            routing_decision=rd,
            model_ids=model_ids,
            tier=tier,
            model_used=None,
            call_meta=None,
        )
        return result

    call_meta: Dict[str, Any] = {"endpoint_role": "map", "benchmark_system": True}
    t0 = time.perf_counter()
    try:
        text, model_used, llm_timing = models_mod.call_chat_with_fallback(
            model_ids,
            messages,
            temperature=float(temperature),
            max_tokens=int(max_tokens),
            return_timing=True,
            call_meta=call_meta,
        )
        answer = models_mod.strip_outer_markdown_fence(text)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        timing = llm_timing or {}
        ttft_raw = timing.get("ttft_ms")
        ttft_ms: Optional[float]
        if ttft_raw is None or float(ttft_raw) <= 0:
            ttft_ms = None
        else:
            ttft_ms = float(ttft_raw)

        # Prefer API usage from call_meta when present; else heuristic.
        usage = {}
        for key in ("usage", "last_usage", "token_usage"):
            if isinstance(call_meta.get(key), dict):
                usage = dict(call_meta[key])
                break

        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or 0)
        if prompt_tokens <= 0:
            prompt_blob = "\n".join(m.get("content") or "" for m in messages)
            prompt_tokens = _estimate_tokens_fallback(prompt_blob)
            usage["prompt_tokens_source"] = "heuristic_fallback"
        else:
            usage["prompt_tokens_source"] = "api"
        if completion_tokens <= 0:
            completion_tokens = _estimate_tokens_fallback(answer)
            usage["completion_tokens_source"] = "heuristic_fallback"
        else:
            usage["completion_tokens_source"] = "api"
        if total_tokens <= 0:
            total_tokens = prompt_tokens + completion_tokens

        cost_model = model_used or (model_ids[0] if model_ids else "")
        result.ok = True
        result.answer = answer or ""
        result.model_returned = model_used
        result.finish_reason = timing.get("finish_reason") or call_meta.get(
            "finish_reason"
        )
        result.latency_ms = float(latency_ms)
        result.ttft_ms = ttft_ms
        result.prompt_tokens = prompt_tokens
        result.completion_tokens = completion_tokens
        result.total_tokens = total_tokens
        result.tokens_per_sec = _tokens_per_sec(completion_tokens, latency_ms)
        result.usage_raw = usage
        result.estimated_api_cost_usd = estimate_api_cost_usd(
            cost_model, prompt_tokens, completion_tokens
        )
        result.provider_metadata = {
            "provider": "nvidia_nim",
            "llm_timing": timing,
            "generation_model": model_used,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        result.routing = _routing_metadata(
            routing_decision=rd,
            model_ids=model_ids,
            tier=tier,
            model_used=model_used,
            call_meta=call_meta,
        )
        result.energy_tier = energy_tier_for_model(cost_model)
        _attach_energy(
            result,
            query=question,
            context_tokens=context_tokens,
            retrieval_hits=retrieval_hits,
            inference_model=cost_model,
        )
        return result
    except Exception as e:
        result.error = str(e)
        result.latency_ms = (time.perf_counter() - t0) * 1000.0
        result.routing = _routing_metadata(
            routing_decision=rd,
            model_ids=model_ids,
            tier=tier,
            model_used=None,
            call_meta=call_meta,
        )
        return result
