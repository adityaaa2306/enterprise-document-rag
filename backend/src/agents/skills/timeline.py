"""Timeline skill — ordered events from context (basic; expand in later phases)."""
from __future__ import annotations

from typing import Dict, List

from src.agents.skills.registry import SkillSpec, register
from src.context.assembler import ContextPack


def build_messages(query: str, pack: ContextPack) -> List[Dict[str, str]]:
    context = pack.context_text or ""
    user = f"""From the context, extract a chronological timeline relevant to the query.
Use bullet points with dates/order when available. If dates are missing, order by
narrative sequence and note uncertainty. Cite [n] markers. If insufficient evidence,
say so.

QUERY:
{query}

CONTEXT:
{context}

TIMELINE:"""
    return [
        {
            "role": "system",
            "content": (
                "You extract timelines from provided context only. "
                "Do not invent dates or events."
            ),
        },
        {"role": "user", "content": user},
    ]


register(
    SkillSpec(
        name="timeline",
        description="Chronological event list from context",
        build_messages=build_messages,
        max_tokens=1500,
        temperature=0.2,
    )
)
