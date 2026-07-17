"""
Frozen prompt templates for GPT benchmarking.

Kept inside the eval package so production ResponseAgent / skill registry
is never invoked for benchmark generation. Prompt text is versioned via
PROMPT_VERSION.
"""
from __future__ import annotations

from typing import Dict, List

from src.eval.gpt_benchmark.versions import PROMPT_VERSION

SYSTEM_PROMPT = (
    "Grounded Q&A assistant. Use only the context. No invented facts. "
    "GFM Markdown."
)

USER_TEMPLATE = """Answer using only the context. Be concise and factual. If insufficient, say so. Cite [n] when useful.

CONTEXT:
{context}

QUERY: {query}"""


def build_frozen_messages(query: str, context_text: str) -> List[Dict[str, str]]:
    """Build identical chat messages for every benchmark model."""
    user = USER_TEMPLATE.format(context=context_text or "", query=query or "")
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def prompt_metadata() -> Dict[str, str]:
    return {
        "prompt_version": PROMPT_VERSION,
        "system_prompt": SYSTEM_PROMPT,
        "user_template": USER_TEMPLATE,
    }
