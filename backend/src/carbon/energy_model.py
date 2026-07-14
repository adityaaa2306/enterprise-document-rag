"""
Operational energy model (Boundary A).

Converts workflow token/stage work into facility electricity (kWh) using:

    E_compute (J)  = Σ tokens × J/token
    E_facility (J) = E_compute × PUE × INFRASTRUCTURE_FACTOR
    E (kWh)        = E_facility / 3_600_000

No BASELINE_SERVING_OVERHEAD or other silent inflation multipliers.
All constants live in ``src.carbon.assumptions`` with citations.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from src.carbon import assumptions as A


def estimate_tokens(text: str) -> int:
    """Rough token estimate when provider counts are unavailable."""
    n = max(0, A.CHARS_PER_TOKEN_ESTIMATE)
    return max(0, len(text or "") // n)


def chars_to_tokens(chars: int) -> int:
    n = max(1, A.CHARS_PER_TOKEN_ESTIMATE)
    return max(0, int(chars or 0) // n)


def joules_to_kwh(joules: float) -> float:
    return float(joules or 0.0) / A.JOULES_PER_KWH


def apply_facility_overhead(compute_joules: float) -> float:
    """IT compute joules → facility joules via PUE × infrastructure factor."""
    return float(compute_joules or 0.0) * float(A.PUE) * float(A.INFRASTRUCTURE_FACTOR)


def energy_to_co2e_g(energy_kwh: float, intensity_gco2_kwh: float) -> float:
    return float(energy_kwh or 0.0) * float(intensity_gco2_kwh or 0.0)


def _tier_jpt(tier: str, table: Mapping[str, float]) -> float:
    key = (tier or A.BASELINE_INFERENCE_TIER).lower()
    if key in table:
        return float(table[key])
    return float(table.get(A.BASELINE_INFERENCE_TIER, A.GPT4O_MINI_J_PER_TOKEN_TYPICAL))


def inference_joules(
    tokens: int,
    *,
    tier: str = "medium",
    j_per_token: Optional[Mapping[str, float]] = None,
) -> float:
    tok = max(0, int(tokens or 0))
    table = j_per_token or A.J_PER_TOKEN_TYPICAL
    return tok * _tier_jpt(tier, table)


def baseline_retrieved_tokens(
    input_tokens: int, total_chunks: int, avg_chunk_tokens: int
) -> int:
    """Only top retrieved chunks — not the entire vector store."""
    if avg_chunk_tokens <= 0 and total_chunks > 0 and input_tokens > 0:
        avg_chunk_tokens = max(1, input_tokens // max(1, total_chunks))
    k = min(max(1, int(total_chunks or 1)), A.BASELINE_RETRIEVED_CHUNK_CAP)
    return int(k * max(1, int(avg_chunk_tokens or 350)))


def _stage_pack(
    *,
    parsing_j: float,
    chunking_j: float,
    embedding_j: float,
    retrieval_j: float,
    routing_j: float,
    inference_j: float,
    verification_j: float,
) -> Dict[str, float]:
    compute = (
        parsing_j
        + chunking_j
        + embedding_j
        + retrieval_j
        + routing_j
        + inference_j
        + verification_j
    )
    facility = apply_facility_overhead(compute)
    # Infrastructure overhead portion = facility − compute (PUE−1 share).
    infrastructure_j = max(0.0, facility - compute)
    return {
        "parsing_j": parsing_j,
        "chunking_j": chunking_j,
        "embedding_j": embedding_j,
        "retrieval_j": retrieval_j,
        "routing_j": routing_j,
        "inference_j": inference_j,
        "verification_j": verification_j,
        "compute_j": compute,
        "infrastructure_j": infrastructure_j,
        "facility_j": facility,
        "total_kwh": joules_to_kwh(facility),
        # Back-compat aliases used by older breakdown consumers
        "parsing_wh": joules_to_kwh(apply_facility_overhead(parsing_j)) * 1000.0,
        "embedding_wh": joules_to_kwh(apply_facility_overhead(embedding_j)) * 1000.0,
        "retrieval_wh": joules_to_kwh(apply_facility_overhead(retrieval_j)) * 1000.0,
        "routing_wh": joules_to_kwh(apply_facility_overhead(routing_j)) * 1000.0,
        "inference_wh": joules_to_kwh(apply_facility_overhead(inference_j)) * 1000.0,
        "verification_wh": joules_to_kwh(apply_facility_overhead(verification_j)) * 1000.0,
        "total_wh": joules_to_kwh(facility) * 1000.0,
    }


def estimate_baseline_energy(
    *,
    input_tokens: int,
    retrieved_context_tokens: int,
    generated_tokens: int,
    map_tokens: Optional[int] = None,
    compile_tokens: Optional[int] = None,
    verification_tokens: int = 0,
    baseline_j_per_token: Optional[float] = None,
    j_per_token: Optional[Mapping[str, float]] = None,
) -> Dict[str, float]:
    """
    Naive conventional pipeline: ONE frontier model for all map + compile
    inference. No CRE / light / medium routing.

    Shared stages (parse/chunk/embed/retrieve/verify) match the optimized
    path; only inference intensity differs (always frontier/heavy).
    """
    inp = max(0, int(input_tokens or 0))
    ret = max(0, int(retrieved_context_tokens or 0))
    gen = max(0, int(generated_tokens or 0))

    parsing_j = inp * A.PARSING_J_PER_TOKEN
    chunking_j = inp * A.CHUNKING_J_PER_TOKEN
    embedding_j = inp * A.EMBEDDING_J_PER_TOKEN
    hits = ret / max(1, 350)
    retrieval_j = A.RETRIEVAL_BASE_J + hits * A.RETRIEVAL_J_PER_HIT
    # No smart routing in the naive baseline.
    routing_j = 0.0

    map_tok = (
        max(0, int(map_tokens))
        if map_tokens is not None
        else (max(int(inp * 1.25), inp) if inp > 0 else 0)
    )
    comp_tok = max(0, int(compile_tokens if compile_tokens is not None else gen))
    verify_tok = max(0, int(verification_tokens or 0))

    if baseline_j_per_token is not None:
        j_ref = float(baseline_j_per_token)
        map_j = map_tok * j_ref
        compile_j = comp_tok * j_ref
    else:
        table = j_per_token or A.J_PER_TOKEN_TYPICAL
        map_j = inference_joules(map_tok, tier=A.BASELINE_INFERENCE_TIER, j_per_token=table)
        compile_j = inference_joules(
            comp_tok, tier=A.BASELINE_INFERENCE_TIER, j_per_token=table
        )

    inference_j = map_j + compile_j
    verification_j = verify_tok * A.VERIFY_J_PER_TOKEN

    pack = _stage_pack(
        parsing_j=parsing_j,
        chunking_j=chunking_j,
        embedding_j=embedding_j,
        retrieval_j=retrieval_j,
        routing_j=routing_j,
        inference_j=inference_j,
        verification_j=verification_j,
    )
    pack["map_inference_j"] = map_j
    pack["compile_inference_j"] = compile_j
    pack["effective_tokens"] = float(inp + ret + gen)
    pack["map_tokens"] = float(map_tok)
    pack["compile_tokens"] = float(comp_tok)
    return pack


def estimate_green_energy(
    *,
    input_tokens: int,
    retrieved_context_tokens: int,
    generated_tokens: int,
    map_tokens_by_tier: Mapping[str, int],
    compile_tokens: int,
    compile_tier: str,
    chunks_escalated: int = 0,
    verification_tokens: int = 0,
    j_per_token: Optional[Mapping[str, float]] = None,
    include_routing: bool = True,
) -> Dict[str, float]:
    """Optimized pipeline: charge stages/models actually used (per-tier map)."""
    inp = max(0, int(input_tokens or 0))
    ret = max(0, int(retrieved_context_tokens or 0))
    gen = max(0, int(generated_tokens or 0))

    parsing_j = inp * A.PARSING_J_PER_TOKEN
    chunking_j = inp * A.CHUNKING_J_PER_TOKEN
    embedding_j = inp * A.EMBEDDING_J_PER_TOKEN
    hits = ret / max(1, 350)
    retrieval_j = A.RETRIEVAL_BASE_J + hits * A.RETRIEVAL_J_PER_HIT
    routing_j = A.ROUTING_BASE_J if include_routing else 0.0

    map_j = 0.0
    for tier, tok in (map_tokens_by_tier or {}).items():
        map_j += inference_joules(int(tok or 0), tier=str(tier), j_per_token=j_per_token)

    compile_j = inference_joules(
        max(0, int(compile_tokens or 0)),
        tier=compile_tier or "heavy",
        j_per_token=j_per_token,
    )
    inference_j = map_j + compile_j

    verification_j = max(0, int(verification_tokens or 0)) * A.VERIFY_J_PER_TOKEN
    if chunks_escalated:
        # Small CPU re-queue cost per escalated chunk (not an LLM call).
        verification_j += int(chunks_escalated) * 2.0

    pack = _stage_pack(
        parsing_j=parsing_j,
        chunking_j=chunking_j,
        embedding_j=embedding_j,
        retrieval_j=retrieval_j,
        routing_j=routing_j,
        inference_j=inference_j,
        verification_j=verification_j,
    )
    pack["map_inference_j"] = map_j
    pack["compile_inference_j"] = compile_j
    pack["generated_tokens_accounted"] = float(gen)
    return pack


# Back-compat wrappers expected by older tests / imports
def estimate_baseline_energy_wh(**kwargs: Any) -> Dict[str, float]:
    return estimate_baseline_energy(**kwargs)


def estimate_green_energy_wh(**kwargs: Any) -> Dict[str, float]:
    return estimate_green_energy(**kwargs)


def wh_to_kwh(wh: float) -> float:
    return float(wh or 0.0) / 1000.0


# Re-export calibration anchors for methodology strings / tests
GPT4O_MINI_MEDIUM_WH = A._GPT4O_MINI_WH
GPT4O_MINI_REF_TOKENS = A._GPT4O_MINI_REF_TOKENS
BASELINE_RETRIEVED_CHUNK_CAP = A.BASELINE_RETRIEVED_CHUNK_CAP
