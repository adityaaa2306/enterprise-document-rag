"""
Frozen summarization prompt templates (eval-only).

Wording mirrors production ``run_tier_summarizer`` system/user shapes so the
Intelligent Router participant exercises the same summarization instruction
surface — without importing or modifying production prompt constants.
"""
from __future__ import annotations

from typing import Dict, List

from src.eval.gpt_benchmark.versions import SUMMARIZE_PROMPT_VERSION

SYSTEM_PROMPT = (
    "You are an expert summarization model. Provide a concise, factual summary "
    "in clean GitHub-Flavored Markdown (headings, bullets, bold where helpful). "
    "Do not add preamble, introduction, or conversational fluff. "
    "Never wrap the whole answer in a code fence. Never output HTML."
)

USER_TEMPLATE = (
    "Summarize the following text factually and concisely in GitHub-Flavored Markdown.\n"
    "Use short paragraphs and bullets when helpful. Do not wrap the whole answer in a "
    "code fence.\n\n"
    "TEXT:\n{text}\n\nSUMMARY:"
)

# Stable task label stored in campaign artifacts (maps to Question Explorer field).
SUMMARIZATION_TASK_LABEL = "Generate a document summary"


def build_summarization_messages(document_text: str) -> List[Dict[str, str]]:
    user = USER_TEMPLATE.format(text=document_text or "")
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def prompt_metadata() -> Dict[str, str]:
    return {
        "prompt_version": SUMMARIZE_PROMPT_VERSION,
        "system_prompt": SYSTEM_PROMPT,
        "user_template": USER_TEMPLATE,
        "task_label": SUMMARIZATION_TASK_LABEL,
    }
