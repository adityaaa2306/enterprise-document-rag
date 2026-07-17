"""
Offline GPT benchmarking framework.

Isolated from the production RAG / routing / carbon paths. Import and run
only via ``run_benchmark.py`` or the gated developer endpoint — never from
normal Interactive RAG or document-processing code.
"""

from src.eval.gpt_benchmark.versions import (
    BENCHMARK_VERSION,
    DOCUMENT_FREEZE_VERSION,
    PROMPT_VERSION,
    RETRIEVAL_VERSION,
    SUMMARIZE_PROMPT_VERSION,
)

__all__ = [
    "BENCHMARK_VERSION",
    "PROMPT_VERSION",
    "RETRIEVAL_VERSION",
    "SUMMARIZE_PROMPT_VERSION",
    "DOCUMENT_FREEZE_VERSION",
]

# Methodology note (v1.4.0):
# - Interactive RAG: retrieve once → freeze prompt/context hashes →
#   consistency gate → Intelligent Router + GPT participants.
# - Document Summarization: freeze stored chunks + summarization prompt →
#   same participants / quality / campaign artifacts.
# System runner uses in-process NIM + stored RoutingDecision (no production HTTP).
