"""Summarize-excerpt skill — concise summary of retrieved context."""
from __future__ import annotations

from typing import Dict, List

from src.agents.skills.registry import SkillSpec, register
from src.context.assembler import ContextPack


def build_messages(query: str, pack: ContextPack) -> List[Dict[str, str]]:
    context = pack.context_text or ""
    user = f"""Summarize the following context to answer the user's request.
Stay faithful to the source text. Be concise. Use citation markers [n] when useful.

USER REQUEST:
{query}

CONTEXT:
{context}

SUMMARY:"""
    return [
        {
            "role": "system",
            "content": (
                "You are an expert summarizer. Produce a faithful, concise summary "
                "of the provided context only."
            ),
        },
        {"role": "user", "content": user},
    ]


register(
    SkillSpec(
        name="summarize_excerpt",
        description="Summarize retrieved excerpts for the user request",
        build_messages=build_messages,
        max_tokens=1200,
        temperature=0.2,
    )
)
