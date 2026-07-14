"""QA skill — grounded question answering over ContextPack."""
from __future__ import annotations

from typing import Dict, List

from src.agents.prompting import MARKDOWN_OUTPUT_RULES
from src.agents.skills.registry import SkillSpec, register
from src.context.assembler import ContextPack


def build_messages(query: str, pack: ContextPack) -> List[Dict[str, str]]:
    context = pack.context_text or ""
    concise = bool((pack.stats or {}).get("concise_prompt"))
    structure = "" if concise else "\nUse ## Summary / Key findings only if helpful.\n"
    user = f"""Answer using only the context. Be concise and factual. If insufficient, say so. Cite [n] when useful.
{MARKDOWN_OUTPUT_RULES}{structure}
CONTEXT:
{context}

QUERY: {query}"""
    return [
        {
            "role": "system",
            "content": "Grounded Q&A assistant. Use only the context. No invented facts. GFM Markdown.",
        },
        {"role": "user", "content": user},
    ]


register(
    SkillSpec(
        name="qa",
        description="Grounded question answering",
        build_messages=build_messages,
        max_tokens=500,  # overridden by response planner
        temperature=0.2,
    )
)
