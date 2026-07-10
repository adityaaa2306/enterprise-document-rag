"""Phase 2.D — Response Agent unit tests (no NIM required)."""
import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.agents.response_agent import (
    ResponseAgent,
    classify_intent,
    resolve_model_chain,
)
from src.agents.skills.registry import ensure_builtins_loaded, get_skill, list_skills
from src.context.assembler import ContextPack, PackedPassage
from src.core.config import settings


def test_classify_intent_defaults_to_qa():
    assert classify_intent("What is the carbon intensity?") == "qa"
    assert classify_intent("") == settings.RESPONSE_DEFAULT_SKILL


def test_classify_intent_summarize():
    assert classify_intent("Please summarize the emissions section") == "summarize_excerpt"
    assert classify_intent("Give me a TLDR") == "summarize_excerpt"


def test_classify_intent_timeline():
    assert classify_intent("Build a timeline of events") == "timeline"
    assert classify_intent("When did the policy change?") == "timeline"


def test_unknown_skill_falls_back_to_qa():
    ensure_builtins_loaded()
    assert get_skill("qa") is not None
    assert "qa" in list_skills()
    assert "summarize_excerpt" in list_skills()


def test_resolve_model_chain_uses_compile_fallbacks():
    rd = {
        "compile_fallbacks": ["model-a", "model-b"],
        "compile_tier": "heavy",
        "tier": "medium",
        "selected_model": "model-map",
        "fallbacks": ["model-map"],
    }
    chain, tier = resolve_model_chain(rd)
    assert chain[0] == "model-a"
    assert chain[1] == "model-b"
    assert tier == "heavy"
    # Heavy settings models appended as safety net
    for m in settings.heavy_models():
        assert m in chain


def test_resolve_model_chain_without_routing():
    chain, tier = resolve_model_chain(None)
    assert chain == list(settings.heavy_models())
    assert tier == "heavy"


def test_prompt_assembly_from_context_pack():
    ensure_builtins_loaded()
    skill = get_skill("qa")
    pack = ContextPack(
        context_text="[1] Section: Intro\nCarbon is high.",
        passages=[
            PackedPassage(
                content="Carbon is high.",
                chunk_ids=["c0"],
                citation=1,
            )
        ],
    )
    messages = skill.build_messages("How high is carbon?", pack)
    assert len(messages) == 2
    assert "Carbon is high" in messages[1]["content"]
    assert "How high is carbon?" in messages[1]["content"]


def test_response_agent_mock_nim():
    pack = ContextPack(
        context_text="[1]\nThe grid intensity is 700 gCO2/kWh.",
        passages=[
            PackedPassage(content="The grid intensity is 700 gCO2/kWh.", chunk_ids=["x"], citation=1)
        ],
        tokens_used=20,
        tokens_budget=6000,
    )
    with patch("src.agents.models.get_nim_client", return_value=object()):
        with patch(
            "src.agents.models.call_chat_with_fallback",
            return_value=("Intensity is 700.", "mock-model-1"),
        ) as mock_chat:
            result = ResponseAgent().answer(
                "What is the intensity?",
                pack=pack,
                routing_decision={
                    "compile_fallbacks": ["mock-model-1", "mock-model-2"],
                    "compile_tier": "heavy",
                },
            )
    assert result.answer == "Intensity is 700."
    assert result.model_used == "mock-model-1"
    assert result.skill == "qa"
    assert result.sources
    mock_chat.assert_called_once()
    args, kwargs = mock_chat.call_args
    assert args[0][0] == "mock-model-1"


def test_response_agent_unknown_intent_uses_qa_skill():
    pack = ContextPack(
        context_text="[1]\nHello world evidence.",
        passages=[PackedPassage(content="Hello world evidence.", chunk_ids=["a"], citation=1)],
    )
    with patch("src.agents.models.get_nim_client", return_value=object()):
        with patch(
            "src.agents.models.call_chat_with_fallback",
            return_value=("Hi.", "m1"),
        ):
            result = ResponseAgent().answer(
                "Explain this document detail",
                pack=pack,
                skill_name="does_not_exist",
            )
    assert result.skill == "qa"


def test_config_flags():
    assert hasattr(settings, "USE_RESPONSE_AGENT")
    assert hasattr(settings, "RESPONSE_DEFAULT_SKILL")
    assert hasattr(settings, "RESPONSE_USE_ROUTING_DECISION")


if __name__ == "__main__":
    test_classify_intent_defaults_to_qa()
    test_classify_intent_summarize()
    test_classify_intent_timeline()
    test_unknown_skill_falls_back_to_qa()
    test_resolve_model_chain_uses_compile_fallbacks()
    test_resolve_model_chain_without_routing()
    test_prompt_assembly_from_context_pack()
    test_response_agent_mock_nim()
    test_response_agent_unknown_intent_uses_qa_skill()
    test_config_flags()
    print("All Phase 2.D response agent tests passed.")
