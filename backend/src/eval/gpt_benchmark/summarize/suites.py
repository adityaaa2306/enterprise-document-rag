"""
Summarization campaign suite profiles.

Suites control how much of the frozen document is included and generation
budgets — never per-participant differences.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from src.eval.gpt_benchmark.workloads import normalize_suite


@dataclass(frozen=True)
class SummarizationSuite:
    suite_id: str
    label: str
    max_chunks: int | None  # None = all chunks
    max_chars: int | None  # None = no char cap after chunk selection
    max_tokens: int
    temperature: float
    description: str


_SUITES: Dict[str, SummarizationSuite] = {
    "summarization-smoke": SummarizationSuite(
        suite_id="summarization-smoke",
        label="Summarization smoke",
        max_chunks=12,
        max_chars=12_000,
        max_tokens=500,
        temperature=0.3,
        description="Small frozen excerpt — quick credit / pipeline check.",
    ),
    "summarization-standard": SummarizationSuite(
        suite_id="summarization-standard",
        label="Summarization standard",
        max_chunks=40,
        max_chars=40_000,
        max_tokens=800,
        temperature=0.3,
        description="Standard frozen document window for routine campaigns.",
    ),
    "summarization-large": SummarizationSuite(
        suite_id="summarization-large",
        label="Summarization large",
        max_chunks=None,
        max_chars=80_000,
        max_tokens=1200,
        temperature=0.3,
        description="Large frozen window (char-capped) for stress comparison.",
    ),
}


def suite_profile(suite: str) -> SummarizationSuite:
    key = normalize_suite(suite)
    if key not in _SUITES:
        raise ValueError(
            f"Unknown summarization suite {suite!r}. "
            f"Choose one of: {', '.join(sorted(_SUITES))}."
        )
    return _SUITES[key]


def list_summarization_suites() -> list[str]:
    return sorted(_SUITES.keys())
