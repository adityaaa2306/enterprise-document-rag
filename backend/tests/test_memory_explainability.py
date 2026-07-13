"""Phase 2.H — MemoryService + ExplainabilityBuilder unit tests."""
import sys
import os
import tempfile
import shutil
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.memory.service import MemoryService, ConversationState
from src.explainability.builder import ExplainabilityBuilder, AnswerEnvelope
from src.context.assembler import ContextPack, PackedPassage
from src.core.config import settings


def test_conversation_ttl_and_prior_entities():
    root = tempfile.mkdtemp()
    old_path = settings.VECTOR_DB_PATH
    old_ttl = settings.CONVERSATION_TTL_HOURS
    old_persist = settings.PERSIST_CONVERSATIONS_TO_DB
    settings.VECTOR_DB_PATH = root
    settings.CONVERSATION_TTL_HOURS = 24
    settings.PERSIST_CONVERSATIONS_TO_DB = False  # exercise file TTL path
    try:
        mem = MemoryService()
        state = mem.start_conversation("doc-1")
        cid = state.conversation_id
        mem.append_turn(cid, "user", "Who is Acme?", entities=[])
        mem.append_turn(cid, "assistant", "Acme is an org.", entities=["acme", "policy"])
        priors = mem.prior_entity_resolutions(cid)
        assert "acme" in priors
        assert "policy" in priors

        # Expire
        settings.CONVERSATION_TTL_HOURS = 0.000001
        time.sleep(0.01)
        assert mem.get_conversation(cid) is None
        assert mem.prior_entity_resolutions(cid) == []
    finally:
        settings.VECTOR_DB_PATH = old_path
        settings.CONVERSATION_TTL_HOURS = old_ttl
        settings.PERSIST_CONVERSATIONS_TO_DB = old_persist
        shutil.rmtree(root, ignore_errors=True)


def test_envelope_builder_from_pack():
    pack = ContextPack(
        context_text="[1]\nAcme announced a policy.\n\n[2]\nMore detail here.",
        passages=[
            PackedPassage(
                content="Acme announced a policy.",
                chunk_ids=["doc_0", "doc_0b"],  # merged siblings — must not fan out
                score=0.02,  # RRF-like raw score
                section_path="(preamble)",
                citation=1,
            ),
            PackedPassage(
                content="More detail here about the policy rollout.",
                chunk_ids=["doc_1"],
                score=0.015,
                section_path="2. Methods",
                citation=2,
            ),
        ],
        tokens_used=40,
        tokens_budget=6000,
        stats={"packed": 2},
    )
    env = ExplainabilityBuilder().build(
        answer="Acme announced a policy in the intro.",
        query="What did Acme announce?",
        document_id="doc",
        pack=pack,
        skill="qa",
        model_used="mock-model",
        tier="heavy",
        routing_decision={
            "selected_model": "mock-model",
            "policy_version": "cre-v1.0",
        },
        retrieval_debug={"mode": "hybrid", "graph_seed": True, "seed_ids": ["doc_0"]},
        prior_entities=["acme"],
    )
    assert isinstance(env, AnswerEnvelope)
    assert env.confidence > 0.4
    # One row per packed passage (not per chunk_id)
    assert len(env.retrieved_chunks) == 2
    assert env.retrieved_chunks[0].id == "doc_0"
    assert env.retrieved_chunks[0].citation == 1
    assert env.retrieved_chunks[0].preview and "Acme" in env.retrieved_chunks[0].preview
    # Preamble replaced with a readable label from content
    assert env.retrieved_chunks[0].parent_section != "(preamble)"
    # RRF-like scores mapped into display relevance (not raw 0.02)
    assert env.retrieved_chunks[0].score >= 0.75
    assert env.retrieved_chunks[1].parent_section == "2. Methods"
    assert "acme" in env.entities_used
    assert "retrieve" in env.reasoning_path
    assert "graph_seed" in env.reasoning_path
    assert "context_pack" in env.reasoning_path
    assert "skill:qa" in env.reasoning_path
    assert env.routing_ref and "doc:" in env.routing_ref
    assert env.model and env.model.model_id == "mock-model"
    d = env.to_dict()
    assert "reasoning_path" in d
    assert d["retrieved_chunks"][0]["id"] == "doc_0"
    assert d["retrieved_chunks"][0].get("preview")


def test_envelope_missing_context_on_refusal():
    env = ExplainabilityBuilder().build(
        answer="There is insufficient context to answer.",
        query="What happened?",
        document_id="doc",
        pack=ContextPack(context_text="", passages=[]),
        skill="qa",
        model_used=None,
        tier="heavy",
    )
    assert "model_reported_insufficient_context" in env.missing_context
    assert "no_retrieved_chunks" in env.missing_context
    assert env.confidence < 0.5


def test_config_flags():
    assert hasattr(settings, "EXPLAINABILITY_ENABLED")
    assert hasattr(settings, "CONVERSATION_TTL_HOURS")


def test_rag_response_schema_optional_fields():
    from src.api.schemas import RagQueryResponse

    legacy = RagQueryResponse(
        document_id="d",
        query="q",
        answer="a",
        sources=["s"],
    )
    assert legacy.confidence is None
    assert legacy.reasoning_path is None

    rich = RagQueryResponse(
        document_id="d",
        query="q",
        answer="a",
        sources=["s"],
        confidence=0.8,
        reasoning_path=["retrieve", "explain"],
        entities_used=["e1"],
        routing_ref="d:cre-v1.0:m",
    )
    assert rich.confidence == 0.8
    assert rich.entities_used == ["e1"]


if __name__ == "__main__":
    test_conversation_ttl_and_prior_entities()
    test_envelope_builder_from_pack()
    test_envelope_missing_context_on_refusal()
    test_config_flags()
    test_rag_response_schema_optional_fields()
    print("All Phase 2.H memory/explainability tests passed.")
