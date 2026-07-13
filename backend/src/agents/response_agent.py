"""
Response Agent — query-time cognition (Phase 2.D).

The only query-time agent: intent → skill → routed model chain → answer.
Does not change CRE / intelligent_router scoring.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from src.agents import models
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

    # Also consider map fallbacks if compile empty
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

    # Append remaining heavy models as safety net
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

        if not pack.context_text and not pack.passages:
            return ResponseResult(
                answer="No relevant context found for this query.",
                skill=skill_key,
                intent=intent,
                model_used=None,
                tier=tier,
                sources=[],
                pack=pack,
                debug={"empty_context": True},
            )

        messages = skill.build_messages(query, pack)
        log.info(
            f"ResponseAgent skill={skill_key} intent={intent} tier={tier} "
            f"models={model_ids[:3]}{'...' if len(model_ids) > 3 else ''}"
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
                    debug={"nim_missing": True},
                )

            from src.monitoring.query_latency import (
                STAGE_LLM_TTFT,
                STAGE_LLM_TTLT,
                STAGE_LLM_TOTAL,
            )

            text, model_used, llm_timing = models.call_chat_with_fallback(
                model_ids,
                messages,
                temperature=skill.temperature,
                max_tokens=skill.max_tokens,
                return_timing=True,
            )
            ttft = float(llm_timing.get("ttft_ms") or 0.0)
            ttlt = float(llm_timing.get("ttlt_ms") or ttft)
            return ResponseResult(
                answer=models.strip_outer_markdown_fence(text),
                skill=skill_key,
                intent=intent,
                model_used=model_used,
                tier=tier,
                sources=pack.source_texts,
                pack=pack,
                debug={
                    "model_chain": model_ids,
                    "routing_used": bool(rd),
                    "latency": {
                        "stages_ms": {
                            STAGE_LLM_TTFT: round(ttft, 3),
                            STAGE_LLM_TTLT: round(ttlt, 3),
                            STAGE_LLM_TOTAL: round(ttlt, 3),
                        },
                        "meta": {
                            "llm_timing_mode": llm_timing.get("mode"),
                            "stream_error": llm_timing.get("stream_error"),
                        },
                    },
                },
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
                debug={"error": str(e)},
            )


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
