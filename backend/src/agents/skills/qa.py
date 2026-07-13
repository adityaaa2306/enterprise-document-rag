"""QA skill — grounded question answering over ContextPack."""
from __future__ import annotations

from typing import Dict, List

from src.agents.prompting import MARKDOWN_OUTPUT_RULES
from src.agents.skills.registry import SkillSpec, register
from src.context.assembler import ContextPack


def build_messages(query: str, pack: ContextPack) -> List[Dict[str, str]]:
    context = pack.context_text or ""
    user = f"""Answer the user's query *only* based on the provided context.
Be concise and factual. If the context is insufficient, say so clearly.
Cite evidence using the bracket numbers from the context when helpful (e.g. [1]).

{MARKDOWN_OUTPUT_RULES}

Suggested structure when useful:
## Summary
## Key Findings
## Details
## Sources

CONTEXT:
{context}

QUERY:
{query}

ANSWER:"""
    return [
        {
            "role": "system",
            "content": (
                "You are an expert Q&A assistant. Use only the provided context. "
                "Do not invent facts. Always reply in GitHub-Flavored Markdown."
            ),
        },
        {"role": "user", "content": user},
    ]


register(
    SkillSpec(
        name="qa",
        description="Grounded question answering",
        build_messages=build_messages,
        max_tokens=1500,
        temperature=0.2,
    )
)
