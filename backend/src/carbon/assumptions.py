"""
Operational carbon accounting assumptions (Boundary A).

All numeric constants used by the energy model live here with units,
literature grounding, and explicit scope. No silent calibration knobs.

Primary equation (Boundary A — operational electricity only):

    E_compute (J)  = Σ (tokens_stage × J_per_token_tier)
    E_facility (J) = E_compute × PUE × INFRASTRUCTURE_FACTOR
    E (kWh)        = E_facility / JOULES_PER_KWH
    CO₂e (g)       = E (kWh) × grid_intensity (gCO₂e/kWh)

References
----------
[1] Luccioni et al., "How Hungry is AI? Benchmarking Energy Use of
    Large Language Model Inference", arXiv:2505.09598 (2025).
    GPT-4o mini medium prompt ≈ 1.418 Wh for ~1000 in + 1000 out tokens.
[2] Google, Data Center Efficiency (PUE) disclosures — modern hyperscale
    fleet average PUE often reported near 1.10–1.15.
[3] Uptime Institute Global Data Center Survey — industry PUE context.
[4] GHG Protocol — operational (Scope 2-style) electricity vs embodied/
    lifecycle boundaries.

Reporting boundaries
--------------------
Boundary A (default, implemented): inference + embeddings + light CPU
    parse/chunk amortization + serving electricity via PUE.
    Excludes training, hardware manufacturing, end-of-life.
Boundary B (reserved): + embodied hardware amortized (not implemented).
Boundary C (reserved): + training / full LCA (not implemented).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Mapping


class ReportingBoundary(str, Enum):
    """Future-proof boundary selector. Only A is fully implemented."""

    A_OPERATIONAL = "A_operational"
    B_OPERATIONAL_PLUS_EMBODIED = "B_operational_plus_embodied"  # reserved
    C_FULL_LIFECYCLE = "C_full_lifecycle"  # reserved


# ---------------------------------------------------------------------------
# Unit conversions
# ---------------------------------------------------------------------------

# 1 kWh = 3.6e6 J (exact by SI definition of the watthour).
JOULES_PER_KWH: float = 3_600_000.0

# ---------------------------------------------------------------------------
# Facility overhead
# ---------------------------------------------------------------------------

# Power Usage Effectiveness: facility energy / IT equipment energy.
# Source: modern hyperscale PUE band ~1.10–1.15 [2][3].
# We use 1.15 as a conservative published operational overhead — NOT a
# free parameter tuned to hit a UI gram target.
PUE: float = 1.15

# Additional infrastructure multiplier beyond PUE (cooling already in PUE).
# Keep at 1.0 so we do not invent a second arbitrary inflation factor.
# Reserved for future measured cooling/network overlays when available.
INFRASTRUCTURE_FACTOR: float = 1.0

# Default reporting boundary for all dashboard / API carbon fields.
DEFAULT_REPORTING_BOUNDARY: ReportingBoundary = ReportingBoundary.A_OPERATIONAL

# ---------------------------------------------------------------------------
# Energy intensity — generative inference (Joule / processed token)
# ---------------------------------------------------------------------------
# Derived from [1]: 1.418 Wh ≈ 5104.8 J for ~2000 processed tokens
#   → 5104.8 / 2000 ≈ 2.5524 J/token for GPT-4o-mini-class ("medium").
#
# Tier relatives are engineering judgments vs that mini-class anchor
# (smaller open models use less energy; 70B-class use more). Ranges feed
# optional uncertainty bands — not silent point-mass calibration.

_GPT4O_MINI_WH = 1.418
_GPT4O_MINI_REF_TOKENS = 2000
_J_PER_WH = 3600.0
GPT4O_MINI_J_PER_TOKEN_TYPICAL: float = (
    (_GPT4O_MINI_WH * _J_PER_WH) / float(_GPT4O_MINI_REF_TOKENS)
)  # ≈ 2.5524 J/token

# Typical (point) J/token by routing tier
J_PER_TOKEN_TYPICAL: Dict[str, float] = {
    # ~8B instruct class — substantially below mini-class energy [1 peers]
    "light": 0.85,
    # GPT-4o-mini / ~14B class — literature anchor [1]
    "medium": GPT4O_MINI_J_PER_TOKEN_TYPICAL,
    # ~70B class — higher activation + memory traffic vs mini
    "heavy": 6.5,
    "large": 6.5,  # alias used by orchestrator compile bookkeeping
}

# Uncertainty bands (low / high) around the typical values — same sources,
# reflecting measurement variance and model-family spread in [1].
J_PER_TOKEN_LOW: Dict[str, float] = {
    "light": 0.50,
    "medium": 1.80,
    "heavy": 4.50,
    "large": 4.50,
}
J_PER_TOKEN_HIGH: Dict[str, float] = {
    "light": 1.40,
    "medium": 3.50,
    "heavy": 9.00,
    "large": 9.00,
}

# ---------------------------------------------------------------------------
# Non-generative stages (still Boundary A operational electricity)
# ---------------------------------------------------------------------------

# Embedding models are ≪ generative LLMs. Order-of-magnitude from small
# encoder energy relative to decoder LLMs in public benchmarks (~1%–few %
# of generative J/token). Units: Joule / token embedded.
EMBEDDING_J_PER_TOKEN: float = 0.05

# Local CPU text extraction / triage amortization. Domains below LLM by
# orders of magnitude; included for transparency, not materiality.
PARSING_J_PER_TOKEN: float = 0.002

# Adaptive chunking / segmentation CPU work (hashing, splits, merges).
CHUNKING_J_PER_TOKEN: float = 0.003

# ANN + sparse retrieval fixed cost (Joules) + per hit.
RETRIEVAL_BASE_J: float = 72.0  # ≈ 0.02 Wh
RETRIEVAL_J_PER_HIT: float = 1.8  # ≈ 5e-4 Wh

# Feature extract + CRE router (CPU / small classifier).
ROUTING_BASE_J: float = 54.0  # ≈ 0.015 Wh

# Lexical quality checks (CPU) — not an LLM verifier in this codebase.
VERIFY_J_PER_TOKEN: float = 0.01

# Baseline RAG: only top-k retrieved chunks count as context (not whole DB).
BASELINE_RETRIEVED_CHUNK_CAP: int = 8

# Naive baseline: ONE frontier model for all map + compile inference.
# No CRE / light / medium routing. Configurable reference key:
#   "heavy" | "gpt-4" | "gpt-4o" | "claude-opus" | "gpt-o3"
BASELINE_INFERENCE_TIER: str = "heavy"

# Named frontier J/token references for the naive baseline (and charts).
# "heavy" aliases J_PER_TOKEN_TYPICAL["heavy"].
BASELINE_REFERENCE_J_PER_TOKEN: Dict[str, float] = {
    "heavy": J_PER_TOKEN_TYPICAL["heavy"],
    "gpt-4": J_PER_TOKEN_TYPICAL["heavy"],
    "llama-4-behemoth": J_PER_TOKEN_TYPICAL["heavy"],
    "gpt-o3": 7.5,
    "claude-opus": 6.0,
    "gpt-4o": 4.0,
    "gemini-2.5-pro": 3.8,
    "llama-4-maverick": 2.8,
    "gemma-3": max(J_PER_TOKEN_TYPICAL["light"], 1.6),
}

# Default naive-baseline reference (env override via Settings.CARBON_BASELINE_REFERENCE).
DEFAULT_BASELINE_REFERENCE: str = "heavy"

# Enable low/typical/high uncertainty on API + dashboard when True.
ENABLE_UNCERTAINTY_BANDS: bool = True

# Rough chars/token for local estimates when provider token counts absent.
CHARS_PER_TOKEN_ESTIMATE: int = 4


@dataclass(frozen=True)
class AssumptionSnapshot:
    """Serializable snapshot for API transparency panels."""

    pue: float
    infrastructure_factor: float
    reporting_boundary: str
    j_per_token_typical: Mapping[str, float]
    embedding_j_per_token: float
    parsing_j_per_token: float
    chunking_j_per_token: float
    enable_uncertainty: bool
    references: tuple


ASSUMPTION_REFERENCES: tuple = (
    "arXiv:2505.09598 — How Hungry is AI? (LLM inference energy)",
    "Google Data Center Efficiency / PUE disclosures (~1.10–1.15)",
    "Uptime Institute Global Data Center Survey (industry PUE context)",
    "GHG Protocol — operational electricity vs embodied lifecycle",
)


def assumption_snapshot() -> AssumptionSnapshot:
    return AssumptionSnapshot(
        pue=PUE,
        infrastructure_factor=INFRASTRUCTURE_FACTOR,
        reporting_boundary=DEFAULT_REPORTING_BOUNDARY.value,
        j_per_token_typical=dict(J_PER_TOKEN_TYPICAL),
        embedding_j_per_token=EMBEDDING_J_PER_TOKEN,
        parsing_j_per_token=PARSING_J_PER_TOKEN,
        chunking_j_per_token=CHUNKING_J_PER_TOKEN,
        enable_uncertainty=ENABLE_UNCERTAINTY_BANDS,
        references=ASSUMPTION_REFERENCES,
    )


def j_per_token_table(band: str = "typical") -> Dict[str, float]:
    """Return J/token table for uncertainty band: low|typical|high."""
    key = (band or "typical").lower()
    if key == "low":
        return dict(J_PER_TOKEN_LOW)
    if key == "high":
        return dict(J_PER_TOKEN_HIGH)
    return dict(J_PER_TOKEN_TYPICAL)
