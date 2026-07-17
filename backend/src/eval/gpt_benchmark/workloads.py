"""
Benchmark workload identifiers.

Interactive RAG remains the default. Document Summarization is an additive
workload that reuses the same campaign / artifact / quality machinery.
"""
from __future__ import annotations

from typing import Optional

WORKLOAD_INTERACTIVE_RAG = "interactive_rag"
WORKLOAD_DOCUMENT_SUMMARIZATION = "document_summarization"

SUMMARIZATION_SUITES = frozenset(
    {
        "summarization-smoke",
        "summarization-standard",
        "summarization-large",
        # aliases
        "summarize-smoke",
        "summarize-standard",
        "summarize-large",
    }
)

RAG_SUITES = frozenset({"smoke", "full"})


def normalize_suite(suite: str) -> str:
    key = (suite or "").strip().lower().replace("_", "-")
    aliases = {
        "summarize-smoke": "summarization-smoke",
        "summarize-standard": "summarization-standard",
        "summarize-large": "summarization-large",
    }
    return aliases.get(key, key)


def workload_for_suite(suite: str) -> str:
    s = normalize_suite(suite)
    if s in SUMMARIZATION_SUITES or s.startswith("summarization-"):
        return WORKLOAD_DOCUMENT_SUMMARIZATION
    return WORKLOAD_INTERACTIVE_RAG


def is_summarization_suite(suite: str) -> bool:
    return workload_for_suite(suite) == WORKLOAD_DOCUMENT_SUMMARIZATION


def workload_display_name(workload: Optional[str]) -> str:
    w = (workload or WORKLOAD_INTERACTIVE_RAG).strip().lower()
    if w == WORKLOAD_DOCUMENT_SUMMARIZATION:
        return "Document Summarization"
    return "Interactive RAG"
