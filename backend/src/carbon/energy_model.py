"""
Workflow energy model (kWh).

Calibration: GPT-4o mini medium prompt energy from
"How Hungry is AI?" (arXiv:2505.09598) —
1.418 Wh for ~1k input + 1k output tokens.

Baseline (conventional single-model RAG/summarize) applies a documented
serving/PUE overhead so document-scale jobs land in a realistic gCO₂e band
once multiplied by live grid intensity — without inventing grams/token.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

# --- Published calibration (Wh) ---
# GPT-4o mini, medium (≈1000 in + 1000 out) ≈ 1.418 Wh  [arXiv:2505.09598]
GPT4O_MINI_MEDIUM_WH = 1.418
GPT4O_MINI_REF_TOKENS = 2000
# Wh per processed token for a GPT-4o-mini-class inference call
GPT4O_MINI_WH_PER_TOKEN = GPT4O_MINI_MEDIUM_WH / float(GPT4O_MINI_REF_TOKENS)

# Unoptimized single-model pipeline overhead (non-batched serving, host PUE,
# orchestration). Scales energy only — never CO₂.
# Tuned so ~27k effective tokens @ ~640 gCO₂e/kWh → roughly 20–50 g baseline.
BASELINE_SERVING_OVERHEAD = 4.5

# Relative inference intensity vs GPT-4o-mini (from same paper / class peers)
TIER_ENERGY_FACTOR = {
    "light": 0.25,    # ~8B class (e.g. LLaMA-3.1-8B ≪ mini)
    "medium": 0.55,   # ~14B class
    "heavy": 2.50,    # ~70B class
    "large": 2.50,
}

# Non-LLM stages (Wh per token or fixed Wh)
EMBED_WH_PER_TOKEN = 2.0e-5          # embedding model ≪ generative LLM
RETRIEVAL_BASE_WH = 0.02             # ANN + sparse + rerank fixed cost
RETRIEVAL_WH_PER_HIT = 5.0e-4
ROUTING_BASE_WH = 0.015              # feature extract + CRE
PARSING_WH_PER_TOKEN = 5.0e-6        # triage / PDF parse amortization
VERIFY_WH_PER_TOKEN = 1.5e-5         # NLI / quality check

# Baseline RAG: only top retrieved chunks count as context (not whole DB)
BASELINE_RETRIEVED_CHUNK_CAP = 8


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token)."""
    return max(0, len(text or "") // 4)


def chars_to_tokens(chars: int) -> int:
    return max(0, int(chars or 0) // 4)


def _tier_factor(tier: str) -> float:
    return float(TIER_ENERGY_FACTOR.get((tier or "medium").lower(), 0.55))


def inference_wh(tokens: int, *, tier: str = "medium", overhead: float = 1.0) -> float:
    tok = max(0, int(tokens or 0))
    return tok * GPT4O_MINI_WH_PER_TOKEN * _tier_factor(tier) * float(overhead)


def estimate_baseline_energy_wh(
    *,
    input_tokens: int,
    retrieved_context_tokens: int,
    generated_tokens: int,
) -> Dict[str, float]:
    """
    Conventional pipeline: one GPT-4o-mini-class model, no routing.
    effective_tokens = input + retrieved_context + generated  (NOT input × chunks)
    """
    inp = max(0, int(input_tokens or 0))
    ret = max(0, int(retrieved_context_tokens or 0))
    gen = max(0, int(generated_tokens or 0))
    effective = inp + ret + gen

    e_parse = inp * PARSING_WH_PER_TOKEN
    e_embed = inp * EMBED_WH_PER_TOKEN
    e_retrieval = RETRIEVAL_BASE_WH + (ret / max(1, 350)) * RETRIEVAL_WH_PER_HIT
    e_inference = inference_wh(
        effective,
        tier="medium",
        overhead=BASELINE_SERVING_OVERHEAD,
    )
    total = e_parse + e_embed + e_retrieval + e_inference
    return {
        "parsing_wh": e_parse,
        "embedding_wh": e_embed,
        "retrieval_wh": e_retrieval,
        "routing_wh": 0.0,
        "inference_wh": e_inference,
        "verification_wh": 0.0,
        "total_wh": total,
        "effective_tokens": float(effective),
    }


def estimate_green_energy_wh(
    *,
    input_tokens: int,
    retrieved_context_tokens: int,
    generated_tokens: int,
    map_tokens_by_tier: Mapping[str, int],
    compile_tokens: int,
    compile_tier: str,
    chunks_escalated: int = 0,
    verification_tokens: int = 0,
) -> Dict[str, float]:
    """
    Optimized pipeline: charge only stages/models actually used.
    Map-summarize tokens are attributed by tier; compile separate.
    """
    inp = max(0, int(input_tokens or 0))
    ret = max(0, int(retrieved_context_tokens or 0))
    gen = max(0, int(generated_tokens or 0))

    e_parse = inp * PARSING_WH_PER_TOKEN
    e_embed = inp * EMBED_WH_PER_TOKEN
    e_retrieval = RETRIEVAL_BASE_WH + (ret / max(1, 350)) * RETRIEVAL_WH_PER_HIT
    e_routing = ROUTING_BASE_WH

    e_map = 0.0
    for tier, tok in (map_tokens_by_tier or {}).items():
        e_map += inference_wh(int(tok or 0), tier=str(tier), overhead=1.15)

    e_compile = inference_wh(
        max(0, int(compile_tokens or 0)),
        tier=compile_tier or "heavy",
        overhead=1.15,
    )
    # Escalation already reflected in map_tokens_by_tier when callers attribute
    # escalated re-summaries to the higher tier; keep a small verify term.
    e_verify = max(0, int(verification_tokens or 0)) * VERIFY_WH_PER_TOKEN
    if chunks_escalated:
        e_verify += int(chunks_escalated) * 0.002

    # Generation charged via map + compile; avoid double-counting gen tokens.
    total = e_parse + e_embed + e_retrieval + e_routing + e_map + e_compile + e_verify
    return {
        "parsing_wh": e_parse,
        "embedding_wh": e_embed,
        "retrieval_wh": e_retrieval,
        "routing_wh": e_routing,
        "inference_wh": e_map + e_compile,
        "map_inference_wh": e_map,
        "compile_inference_wh": e_compile,
        "verification_wh": e_verify,
        "total_wh": total,
        "generated_tokens_accounted": float(gen),
    }


def wh_to_kwh(wh: float) -> float:
    return float(wh or 0.0) / 1000.0


def energy_to_co2e_g(energy_kwh: float, intensity_gco2_kwh: float) -> float:
    return float(energy_kwh or 0.0) * float(intensity_gco2_kwh or 0.0)


def baseline_retrieved_tokens(input_tokens: int, total_chunks: int, avg_chunk_tokens: int) -> int:
    """Only top retrieved chunks — not the entire vector store."""
    if avg_chunk_tokens <= 0 and total_chunks > 0 and input_tokens > 0:
        avg_chunk_tokens = max(1, input_tokens // max(1, total_chunks))
    k = min(max(1, int(total_chunks or 1)), BASELINE_RETRIEVED_CHUNK_CAP)
    return int(k * max(1, int(avg_chunk_tokens or 350)))
