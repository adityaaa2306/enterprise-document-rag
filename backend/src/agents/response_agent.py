"""
Response Agent — query-time cognition (Phase 2.D).

The only query-time agent: intent → skill → routed model chain → answer.
Does not change CRE / intelligent_router scoring.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, List, Optional, Sequence, Tuple

from src.agents import models
from src.agents.response_planner import classify_response_length
from src.agents.skills.registry import ensure_builtins_loaded, get_skill
from src.context.assembler import ContextAssembler, ContextPack, assemble_context
from src.core.config import settings

log = logging.getLogger(__name__)


@dataclass
class ResponseResult:
    answer: str
    skill: str
    intent: str
    model_used: Optional[str] = None
    tier: str = "heavy"
    sources: List[str] = field(default_factory=list)
    pack: Optional[ContextPack] = None
    debug: Dict[str, Any] = field(default_factory=dict)


_INTENT_SUMMARIZE = re.compile(
    r"\b(summarize|summary|overview|tldr|tl;dr|sum up|brief me)\b",
    re.I,
)
_INTENT_TIMELINE = re.compile(
    r"\b(timeline|chronolog|sequence of events|when did|history of events)\b",
    re.I,
)


def classify_intent(query: str) -> str:
    """Rule-based intent → skill name. Unknown → default skill."""
    q = query or ""
    if _INTENT_SUMMARIZE.search(q):
        return "summarize_excerpt"
    if _INTENT_TIMELINE.search(q):
        return "timeline"
    return settings.RESPONSE_DEFAULT_SKILL or "qa"


def resolve_model_chain(
    routing_decision: Optional[Dict[str, Any]] = None,
) -> tuple[List[str], str]:
    """
    Prefer stored compile_fallbacks / heavy chain from RoutingDecision;
    otherwise fall back to settings.heavy_models().
    """
    heavy = list(settings.heavy_models())
    if not settings.RESPONSE_USE_ROUTING_DECISION or not routing_decision:
        return heavy, "heavy"

    chain: List[str] = []
    compile_fb = routing_decision.get("compile_fallbacks") or []
    if isinstance(compile_fb, list):
        chain.extend([m for m in compile_fb if m])

    if not chain:
        fb = routing_decision.get("fallbacks") or []
        selected = routing_decision.get("selected_model")
        if selected:
            chain.append(selected)
        if isinstance(fb, list):
            for m in fb:
                if m and m not in chain:
                    chain.append(m)

    tier = (
        routing_decision.get("compile_tier")
        or routing_decision.get("tier")
        or "heavy"
    )

    for m in heavy:
        if m not in chain:
            chain.append(m)

    if not chain:
        chain = heavy
        tier = "heavy"

    return chain, str(tier)


def _load_routing(document_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not document_id:
        return None
    try:
        from src.memory import storage

        return storage.get_routing_decision(document_id)
    except Exception as e:
        log.warning(f"Could not load routing_decision for {document_id}: {e}")
        return None


def _pack_from_chunks(chunks: Sequence[Any], tier: str, query: str) -> ContextPack:
    """Build a ContextPack from legacy content chunks when assembler path skipped."""
    passages = []
    for i, c in enumerate(chunks):
        content = getattr(c, "content", None) or (c.get("content") if isinstance(c, dict) else "") or ""
        if not content:
            continue
        passages.append(
            {
                "chunk_id": getattr(c, "chunk_id", None) or f"legacy_{i}",
                "content": content,
                "score": float(getattr(c, "score", 0.0) or 0.0),
                "rank": i,
            }
        )
    return ContextAssembler().pack(passages, tier=tier, query=query)


def _prepare(
    query: str,
    *,
    pack: Optional[ContextPack],
    passages: Optional[Sequence[Any]],
    context_chunks: Optional[Sequence[Any]],
    document_id: Optional[str],
    routing_decision: Optional[Dict[str, Any]],
    skill_name: Optional[str],
) -> Tuple[str, Any, List[str], str, ContextPack, Optional[Dict[str, Any]], List[Dict[str, str]], int, Dict[str, Any]]:
    """Shared setup for answer / answer_stream. Returns skill_key, skill, models, tier, pack, rd, messages, max_tokens, plan_meta."""
    ensure_builtins_loaded()

    intent = classify_intent(query)
    skill_key = skill_name or intent
    skill = get_skill(skill_key)
    if skill is None:
        log.info(f"Unknown skill '{skill_key}'; defaulting to qa")
        skill_key = "qa"
        skill = get_skill("qa")
    assert skill is not None

    rd = routing_decision
    if rd is None and settings.RESPONSE_USE_ROUTING_DECISION:
        rd = _load_routing(document_id)

    model_ids, tier = resolve_model_chain(rd)

    if pack is None:
        if passages is not None:
            pack = assemble_context(passages, tier=tier, query=query)
        elif context_chunks is not None:
            pack = _pack_from_chunks(context_chunks, tier=tier, query=query)
        else:
            pack = ContextPack(context_text="", tokens_budget=0)

    plan = classify_response_length(query)
    max_tokens = min(int(skill.max_tokens or plan.max_tokens), plan.max_tokens)
    # Timeline/summary skills already have tight caps; planner still wins if lower
    if skill_key == "timeline":
        max_tokens = min(max_tokens, plan.max_tokens)
    elif skill_key == "summarize_excerpt":
        max_tokens = min(max_tokens, plan.max_tokens)

    if pack.stats is None:
        pack.stats = {}
    pack.stats["concise_prompt"] = plan.concise
    pack.stats["response_query_type"] = plan.query_type
    pack.stats["response_max_tokens"] = max_tokens

    messages = skill.build_messages(query, pack)
    plan_meta = {
        "query_type": plan.query_type,
        "max_tokens": max_tokens,
        "concise": plan.concise,
        "skill_cap": skill.max_tokens,
    }
    return skill_key, skill, model_ids, tier, pack, rd, messages, max_tokens, plan_meta


def _prompt_token_meta(
    messages: List[Dict[str, str]],
    pack: ContextPack,
    query: str,
    max_tokens: int,
    plan_meta: Dict[str, Any],
    out_tokens: int = 0,
) -> Dict[str, Any]:
    from src.chunking.service import estimate_tokens

    system_text = ""
    user_text = ""
    for m in messages:
        role = (m.get("role") or "").lower()
        content = m.get("content") or ""
        if role == "system":
            system_text += content
        elif role == "user":
            user_text += content

    system_tokens = int(estimate_tokens(system_text) or 0)
    ctx_tokens = int(getattr(pack, "tokens_used", 0) or 0)
    query_tokens = int(estimate_tokens(query) or 0)
    final_prompt_tokens = system_tokens + int(estimate_tokens(user_text) or 0)
    return {
        "system_tokens": system_tokens,
        "user_query_tokens": query_tokens,
        "retrieved_context_tokens": ctx_tokens,
        "final_prompt_tokens": final_prompt_tokens,
        "output_tokens": out_tokens,
        "max_tokens_cap": max_tokens,
        "response_plan": plan_meta,
    }


def _latency_debug(
    llm_timing: Dict[str, Any],
    *,
    model_used: Optional[str],
    model_ids: List[str],
    rd: Optional[Dict[str, Any]],
    call_meta: Dict[str, Any],
    prompt_meta: Dict[str, Any],
    post_ms: float,
    out_tokens: int,
) -> Dict[str, Any]:
    from src.monitoring.query_latency import (
        STAGE_LLM_TTFT,
        STAGE_LLM_TTLT,
        STAGE_LLM_TOTAL,
        STAGE_NIM_NETWORK,
        STAGE_NIM_REQUEST,
        STAGE_POSTPROCESS,
    )

    ttft = float(llm_timing.get("ttft_ms") or 0.0)
    ttlt = float(llm_timing.get("ttlt_ms") or ttft)
    first_byte = float(llm_timing.get("first_byte_ms") or ttft)
    network_ms = float(llm_timing.get("network_ms") or first_byte)
    inference_ms = float(
        llm_timing.get("inference_ms")
        if llm_timing.get("inference_ms") is not None
        else max(0.0, ttlt - first_byte)
    )
    gen_ms = max(0.0, ttlt - ttft)
    tokens_per_sec = round(out_tokens / (gen_ms / 1000.0), 2) if gen_ms > 0 and out_tokens else 0.0

    retry_reasons = [
        a.get("error")
        for a in (llm_timing.get("attempts") or [])
        if not a.get("ok") and a.get("error")
    ]

    prompt_meta = dict(prompt_meta)
    prompt_meta["tokens_per_sec"] = tokens_per_sec
    prompt_meta["generation_ms_after_ttft"] = round(gen_ms, 3)

    return {
        "model_chain": model_ids,
        "routing_used": bool(rd),
        "latency": {
            "stages_ms": {
                STAGE_LLM_TTFT: round(ttft, 3),
                STAGE_LLM_TTLT: round(ttlt, 3),
                STAGE_LLM_TOTAL: round(ttlt, 3),
                STAGE_NIM_REQUEST: round(ttlt, 3),
                STAGE_NIM_NETWORK: round(network_ms, 3),
                STAGE_POSTPROCESS: round(post_ms, 3),
            },
            "meta": {
                "llm_timing_mode": llm_timing.get("mode"),
                "stream_error": llm_timing.get("stream_error"),
                "nim": {
                    "request_start_ms": llm_timing.get("request_start_ms", 0.0),
                    "first_byte_ms": first_byte,
                    "ttft_ms": ttft,
                    "ttlt_ms": ttlt,
                    "inference_ms": round(inference_ms, 3),
                    "network_ms": round(network_ms, 3),
                    "tokens_per_sec": tokens_per_sec,
                    "retry_count": llm_timing.get("retry_count", 0),
                    "retry_reasons": retry_reasons,
                    "fallback_used": llm_timing.get("fallback_used"),
                    "primary_model": llm_timing.get("primary_model"),
                    "model_used": model_used,
                    "http_status": llm_timing.get("http_status"),
                    "attempts": llm_timing.get("attempts") or call_meta.get("attempts"),
                },
                "prompt": prompt_meta,
            },
        },
    }


class ResponseAgent:
    """Intent → skill registry → NIM chat with routed model chain."""

    def answer(
        self,
        query: str,
        *,
        pack: Optional[ContextPack] = None,
        passages: Optional[Sequence[Any]] = None,
        context_chunks: Optional[Sequence[Any]] = None,
        document_id: Optional[str] = None,
        routing_decision: Optional[Dict[str, Any]] = None,
        skill_name: Optional[str] = None,
    ) -> ResponseResult:
        skill_key, skill, model_ids, tier, pack, rd, messages, max_tokens, plan_meta = _prepare(
            query,
            pack=pack,
            passages=passages,
            context_chunks=context_chunks,
            document_id=document_id,
            routing_decision=routing_decision,
            skill_name=skill_name,
        )
        intent = classify_intent(query)

        if not pack.context_text and not pack.passages:
            return ResponseResult(
                answer="No relevant context found for this query.",
                skill=skill_key,
                intent=intent,
                model_used=None,
                tier=tier,
                sources=[],
                pack=pack,
                debug={"empty_context": True, "response_plan": plan_meta},
            )

        log.info(
            "ResponseAgent skill=%s intent=%s type=%s max_tokens=%s tier=%s models=%s%s",
            skill_key,
            intent,
            plan_meta.get("query_type"),
            max_tokens,
            tier,
            model_ids[:3],
            "..." if len(model_ids) > 3 else "",
        )

        try:
            if models.get_nim_client() is None:
                return ResponseResult(
                    answer=(
                        "Error: RAG model not loaded. Please ensure your "
                        "NVIDIA_API_KEY is set."
                    ),
                    skill=skill_key,
                    intent=intent,
                    model_used=None,
                    tier=tier,
                    sources=pack.source_texts,
                    pack=pack,
                    debug={"nim_missing": True, "response_plan": plan_meta},
                )

            from src.chunking.service import estimate_tokens

            prompt_meta = _prompt_token_meta(messages, pack, query, max_tokens, plan_meta)
            call_meta: Dict[str, Any] = {}
            text, model_used, llm_timing = models.call_chat_with_fallback(
                model_ids,
                messages,
                temperature=skill.temperature,
                max_tokens=max_tokens,
                return_timing=True,
                call_meta=call_meta,
            )
            t_post = time.perf_counter()
            answer = models.strip_outer_markdown_fence(text)
            post_ms = (time.perf_counter() - t_post) * 1000.0
            out_tokens = int(estimate_tokens(answer) or 0)
            prompt_meta["output_tokens"] = out_tokens

            debug = _latency_debug(
                llm_timing,
                model_used=model_used,
                model_ids=model_ids,
                rd=rd,
                call_meta=call_meta,
                prompt_meta=prompt_meta,
                post_ms=post_ms,
                out_tokens=out_tokens,
            )
            debug["response_plan"] = plan_meta

            return ResponseResult(
                answer=answer,
                skill=skill_key,
                intent=intent,
                model_used=model_used,
                tier=tier,
                sources=pack.source_texts,
                pack=pack,
                debug=debug,
            )
        except Exception as e:
            log.error(f"ResponseAgent generation failed: {e}")
            return ResponseResult(
                answer="Failed to generate answer.",
                skill=skill_key,
                intent=intent,
                model_used=None,
                tier=tier,
                sources=pack.source_texts,
                pack=pack,
                debug={"error": str(e), "response_plan": plan_meta},
            )

    def answer_stream(
        self,
        query: str,
        *,
        pack: Optional[ContextPack] = None,
        passages: Optional[Sequence[Any]] = None,
        context_chunks: Optional[Sequence[Any]] = None,
        document_id: Optional[str] = None,
        routing_decision: Optional[Dict[str, Any]] = None,
        skill_name: Optional[str] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        """
        Yield SSE-friendly events:
          {"event":"meta", ...}
          {"event":"token", "text": "..."}
          {"event":"done", "answer": "...", "debug": {...}, ...}
          {"event":"error", "message": "..."}
        """
        skill_key, skill, model_ids, tier, pack, rd, messages, max_tokens, plan_meta = _prepare(
            query,
            pack=pack,
            passages=passages,
            context_chunks=context_chunks,
            document_id=document_id,
            routing_decision=routing_decision,
            skill_name=skill_name,
        )
        intent = classify_intent(query)

        yield {
            "event": "meta",
            "skill": skill_key,
            "intent": intent,
            "tier": tier,
            "response_plan": plan_meta,
            "sources": pack.source_texts if pack else [],
        }

        if not pack.context_text and not pack.passages:
            yield {
                "event": "done",
                "answer": "No relevant context found for this query.",
                "skill": skill_key,
                "intent": intent,
                "model_used": None,
                "tier": tier,
                "sources": [],
                "debug": {"empty_context": True, "response_plan": plan_meta},
            }
            return

        if models.get_nim_client() is None:
            yield {
                "event": "error",
                "message": "NVIDIA_API_KEY not configured.",
            }
            return

        from src.chunking.service import estimate_tokens

        prompt_meta = _prompt_token_meta(messages, pack, query, max_tokens, plan_meta)
        parts: List[str] = []
        model_used: Optional[str] = None
        llm_timing: Dict[str, Any] = {}
        call_meta: Dict[str, Any] = {}

        try:
            for kind, payload in models.iter_chat_stream_with_fallback(
                model_ids,
                messages,
                temperature=skill.temperature,
                max_tokens=max_tokens,
                call_meta=call_meta,
            ):
                if kind == "token":
                    parts.append(payload)
                    yield {"event": "token", "text": payload}
                elif kind == "done":
                    model_used = payload.get("model_id")
                    llm_timing = payload.get("timing") or {}
        except Exception as e:
            log.error(f"ResponseAgent stream failed: {e}")
            yield {"event": "error", "message": str(e)}
            return

        t_post = time.perf_counter()
        raw = "".join(parts)
        answer = models.strip_outer_markdown_fence(raw)
        post_ms = (time.perf_counter() - t_post) * 1000.0
        out_tokens = int(estimate_tokens(answer) or 0)
        prompt_meta["output_tokens"] = out_tokens

        debug = _latency_debug(
            llm_timing,
            model_used=model_used,
            model_ids=model_ids,
            rd=rd,
            call_meta=call_meta,
            prompt_meta=prompt_meta,
            post_ms=post_ms,
            out_tokens=out_tokens,
        )
        debug["response_plan"] = plan_meta

        yield {
            "event": "done",
            "answer": answer,
            "skill": skill_key,
            "intent": intent,
            "model_used": model_used,
            "tier": tier,
            "sources": pack.source_texts,
            "debug": debug,
            "pack": pack,
        }


def answer_query(
    query: str,
    *,
    pack: Optional[ContextPack] = None,
    document_id: Optional[str] = None,
    **kwargs: Any,
) -> ResponseResult:
    return ResponseAgent().answer(
        query, pack=pack, document_id=document_id, **kwargs
    )
