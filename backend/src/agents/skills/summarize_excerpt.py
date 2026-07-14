"""Summarize-excerpt skill — concise summary of retrieved context."""
from __future__ import annotations

from typing import Dict, List

from src.agents.prompting import MARKDOWN_OUTPUT_RULES
from src.agents.skills.registry import SkillSpec, register
from src.context.assembler import ContextPack


def build_messages(query: str, pack: ContextPack) -> List[Dict[str, str]]:
    context = pack.context_text or ""
    user = f"""Summarize the context for the request. Stay faithful; be concise; cite [n] when useful.
{MARKDOWN_OUTPUT_RULES}

REQUEST: {query}

CONTEXT:
{context}"""
    return [
        {
            "role": "system",
            "content": "Faithful summarizer. Context only. Concise GFM Markdown.",
        },
        {"role": "user", "content": user},
    ]


register(
    SkillSpec(
        name="summarize_excerpt",
        description="Summarize retrieved excerpts for the user request",
        build_messages=build_messages,
        max_tokens=250,
        temperature=0.2,
    )
)
