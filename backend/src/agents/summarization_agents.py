"""
Thin Light / Medium / Heavy summarization agent wrappers.

Each call returns summary text plus latency, token usage, carbon estimate, confidence.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from src.agents import models
from src.carbon.assumptions import J_PER_TOKEN_TYPICAL, PUE
from src.carbon.energy_model import estimate_tokens, joules_to_kwh


@dataclass
class AgentRunResult:
    summary: str
    tier: str
    model_id: Optional[str]
    latency_ms: float
    input_tokens: int
    output_tokens: int
    carbon_estimate_g: float
    confidence: float
    success: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _estimate_carbon_g(tier: str, in_tok: int, out_tok: int, intensity: float = 500.0) -> float:
    jpt = float(J_PER_TOKEN_TYPICAL.get(tier, J_PER_TOKEN_TYPICAL["medium"]))
    joules = (in_tok + out_tok) * jpt * float(PUE)
    return joules_to_kwh(joules) * float(intensity)


def run_summarization_agent(
    text: str,
    state: Dict[str, Any],
    *,
    tier: str,
    model_ids: Optional[List[str]] = None,
    grid_intensity: float = 500.0,
) -> AgentRunResult:
    """Run the configured tier summarizer and attach telemetry."""
    call_meta: Dict[str, Any] = {}
    t0 = time.perf_counter()
    summary = models.run_tier_summarizer(
        text,
        state,
        tier=tier,
        model_ids=model_ids,
        call_meta=call_meta,
    )
    latency_ms = (time.perf_counter() - t0) * 1000.0
    if call_meta.get("call_ms") is not None:
        latency_ms = float(call_meta["call_ms"])
    in_tok = estimate_tokens(text)
    out_tok = estimate_tokens(str(summary or ""))
    success = bool(call_meta.get("success", True)) and not str(summary).startswith(
        ("Error:", "Summary generation failed")
    )
    conf = 0.9 if success else 0.2
    if len(str(summary or "")) < 40:
        conf = min(conf, 0.45)
    return AgentRunResult(
        summary=str(summary or ""),
        tier=tier,
        model_id=call_meta.get("model_id") or (model_ids[0] if model_ids else None),
        latency_ms=round(latency_ms, 1),
        input_tokens=in_tok,
        output_tokens=out_tok,
        carbon_estimate_g=round(_estimate_carbon_g(tier, in_tok, out_tok, grid_intensity), 4),
        confidence=round(conf, 4),
        success=success,
    )


def run_light_agent(text: str, state: Dict[str, Any], **kwargs: Any) -> AgentRunResult:
    return run_summarization_agent(text, state, tier="light", **kwargs)


def run_medium_agent(text: str, state: Dict[str, Any], **kwargs: Any) -> AgentRunResult:
    return run_summarization_agent(text, state, tier="medium", **kwargs)


def run_heavy_agent(text: str, state: Dict[str, Any], **kwargs: Any) -> AgentRunResult:
    return run_summarization_agent(text, state, tier="heavy", **kwargs)
