"""
List pricing used for estimated API cost (USD per 1M tokens).

OpenAI rates mirror https://developers.openai.com/api/docs/pricing (standard, non-batch).
NIM rates are approximate catalog proxies for offline comparison only — not invoices.
Update when providers revise published prices; estimates are informational only.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

# model_id -> (input_usd_per_1m, output_usd_per_1m)
MODEL_PRICING_USD_PER_1M: Dict[str, Tuple[float, float]] = {
    "gpt-5-nano": (0.05, 0.40),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5.5": (5.00, 30.00),
    # NVIDIA NIM / hosted catalog proxies (benchmark estimates only)
    "meta/llama-3.1-8b-instruct": (0.06, 0.06),
    "meta/llama-3.3-70b-instruct": (0.90, 0.90),
    "mistralai/ministral-14b-instruct-2512": (0.20, 0.20),
    "mistralai/mistral-nemotron": (0.15, 0.15),
    "openai/gpt-oss-120b": (1.20, 1.20),
}

# Map generation models onto existing energy-model tiers (light/medium/heavy).
MODEL_ENERGY_TIER: Dict[str, str] = {
    "gpt-5-nano": "light",
    "gpt-5-mini": "medium",
    "gpt-5.5": "heavy",
    "meta/llama-3.1-8b-instruct": "light",
    "mistralai/mistral-nemotron": "light",
    "mistralai/ministral-14b-instruct-2512": "medium",
    "meta/llama-3.3-70b-instruct": "heavy",
    "openai/gpt-oss-120b": "heavy",
    "intelligent-router": "medium",
}

# Backward-compatible alias (GPT-only default without system participant)
DEFAULT_BENCHMARK_MODELS = ("gpt-5-nano", "gpt-5-mini", "gpt-5.5")


def estimate_api_cost_usd(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    rates = MODEL_PRICING_USD_PER_1M.get(model)
    if rates is None:
        # Prefix / family fallbacks for NIM variants
        mid = (model or "").lower()
        if "8b" in mid or ("nemotron" in mid and "embed" not in mid):
            rates = (0.06, 0.06)
        elif "14b" in mid or "ministral" in mid:
            rates = (0.20, 0.20)
        elif "70b" in mid or "120b" in mid:
            rates = (0.90, 0.90)
        else:
            return 0.0
    inp, out = rates
    return (max(0, prompt_tokens) / 1_000_000.0) * inp + (
        max(0, completion_tokens) / 1_000_000.0
    ) * out


def energy_tier_for_model(model: Optional[str]) -> str:
    if not model:
        return "medium"
    if model in MODEL_ENERGY_TIER:
        return MODEL_ENERGY_TIER[model]
    mid = model.lower()
    if "8b" in mid:
        return "light"
    if "14b" in mid or "ministral" in mid:
        return "medium"
    if "70b" in mid or "120b" in mid:
        return "heavy"
    return "medium"
