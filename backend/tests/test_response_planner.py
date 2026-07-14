"""Adaptive response length planner unit tests."""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.agents.response_planner import classify_response_length, BUDGETS
from src.agents.prompting import MARKDOWN_OUTPUT_RULES
from src.agents.skills.registry import ensure_builtins_loaded, get_skill
from src.context.assembler import ContextPack
from src.chunking.service import estimate_tokens


def test_fact_budget():
    p = classify_response_length("What is the carbon intensity?")
    assert p.query_type == "fact"
    assert p.max_tokens == BUDGETS["fact"]
    assert p.concise is True


def test_summary_budget():
    p = classify_response_length("Summarize this document in one paragraph")
    assert p.query_type == "summary"
    assert p.max_tokens == BUDGETS["summary"]


def test_comparison_budget():
    p = classify_response_length("Compare section 2 versus section 4")
    assert p.query_type == "comparison"
    assert p.max_tokens == BUDGETS["comparison"]


def test_explanation_budget():
    p = classify_response_length("Explain this like I'm a beginner")
    assert p.query_type == "explanation"
    assert p.max_tokens == BUDGETS["explanation"]


def test_analytical_budget():
    p = classify_response_length("Analyze the limitations and trade-offs")
    assert p.query_type == "analytical"
    assert p.max_tokens == BUDGETS["analytical"]


def test_compressed_markdown_rules_are_short():
    toks = estimate_tokens(MARKDOWN_OUTPUT_RULES)
    assert toks < 80, f"MARKDOWN_OUTPUT_RULES still verbose: {toks} tokens"


def test_qa_prompt_smaller_when_concise():
    ensure_builtins_loaded()
    skill = get_skill("qa")
    pack = ContextPack(context_text="[1]\nEvidence here.", passages=[])
    pack.stats = {"concise_prompt": True}
    msgs = skill.build_messages("What is X?", pack)
    assert "Suggested structure" not in msgs[1]["content"]
    assert "CONTEXT:" in msgs[1]["content"]
