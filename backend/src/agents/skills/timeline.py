"""Timeline skill — ordered events from context."""
from __future__ import annotations

from typing import Dict, List

from src.agents.prompting import MARKDOWN_OUTPUT_RULES
from src.agents.skills.registry import SkillSpec, register
from src.context.assembler import ContextPack


def build_messages(query: str, pack: ContextPack) -> List[Dict[str, str]]:
    context = pack.context_text or ""
    user = f"""Extract a chronological timeline for the query from context only. Bullet list with dates/order; note uncertainty; cite [n]. If insufficient, say so.
{MARKDOWN_OUTPUT_RULES}

QUERY: {query}

CONTEXT:
{context}"""
    return [
        {
            "role": "system",
            "content": "Timeline extractor. Context only; no invented dates. GFM Markdown.",
        },
        {"role": "user", "content": user},
    ]


register(
    SkillSpec(
        name="timeline",
        description="Chronological event list from context",
        build_messages=build_messages,
        max_tokens=400,
        temperature=0.2,
    )
)
