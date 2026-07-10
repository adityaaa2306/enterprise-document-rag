"""Phase 2.F — Understanding Agent / grounding unit tests (no NIM required)."""
import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.knowledge.schemas import (
    Entity,
    EvidenceSpan,
    KnowledgeDocument,
    Relation,
    extract_json_object,
    knowledge_from_extraction,
)
from src.validation.service import ValidationService, quote_grounded_in_chunk
from src.agents.understanding_agent import UnderstandingAgent, UnderstandingResult
from src.core.config import settings


def test_extract_json_object_plain():
    data = extract_json_object('{"entities": [{"id": "e1", "name": "Acme"}]}')
    assert data is not None
    assert data["entities"][0]["name"] == "Acme"


def test_extract_json_object_fenced_and_trailing_comma():
    raw = """Here you go:
```json
{
  "entities": [{"id": "e1", "type": "Org", "name": "Acme", "aliases": [], "evidence": []},],
  "concepts": []
}
```
"""
    data = extract_json_object(raw)
    assert data is not None
    assert data["entities"][0]["id"] == "e1"


def test_extract_json_object_invalid():
    assert extract_json_object("not json at all") is None


def test_quote_grounded_substring():
    assert quote_grounded_in_chunk(
        "carbon intensity",
        "The carbon intensity of the grid is high.",
    )
    assert not quote_grounded_in_chunk(
        "totally fabricated claim xyzzy",
        "The carbon intensity of the grid is high.",
    )


def test_grounding_drops_ungrounded_entities():
    chunk_texts = {
        "doc_0": "Acme Corp announced a new carbon policy in 2024.",
        "doc_1": "The grid intensity reached 700 gCO2 per kWh.",
    }
    doc = KnowledgeDocument(
        document_id="doc",
        entities=[
            Entity(
                id="e1",
                type="Org",
                name="Acme Corp",
                evidence=[EvidenceSpan(chunk_id="doc_0", quote="Acme Corp announced")],
            ),
            Entity(
                id="e2",
                type="Org",
                name="FakeCo",
                evidence=[EvidenceSpan(chunk_id="doc_0", quote="does not appear anywhere")],
            ),
            Entity(
                id="e3",
                type="Metric",
                name="Intensity",
                evidence=[],  # no evidence
            ),
        ],
        relations=[
            Relation(id="r1", src="e1", rel="RELATES_TO", dst="e2"),
            Relation(id="r2", src="e1", rel="MENTIONS", dst="e1"),
        ],
    )
    grounded, report = ValidationService().ground_knowledge(doc, chunk_texts)
    assert len(grounded.entities) == 1
    assert grounded.entities[0].id == "e1"
    assert report.dropped_entities == 2
    # r1 dropped (e2 gone); r2 kept (e1→e1)
    assert len(grounded.relations) == 1
    assert grounded.relations[0].id == "r2"
    assert all(e.evidence for e in grounded.entities)


def test_knowledge_from_extraction():
    raw = {
        "entities": [
            {
                "id": "e1",
                "type": "Org",
                "name": "Acme",
                "evidence": [{"chunk_id": "c0", "quote": "Acme"}],
            }
        ],
        "relations": [],
    }
    kd = knowledge_from_extraction("doc1", raw)
    assert kd.document_id == "doc1"
    assert kd.entities[0].name == "Acme"


def test_enable_understanding_false_skips_llm():
    old = settings.ENABLE_UNDERSTANDING
    settings.ENABLE_UNDERSTANDING = False
    try:
        with patch("src.agents.models.call_chat_with_fallback") as mock_chat:
            result = UnderstandingAgent().extract(
                "doc",
                [{"chunk_id": "doc_0", "text": "Hello Acme world."}],
            )
            mock_chat.assert_not_called()
        assert result.document.status == "skipped"
        assert result.debug.get("disabled") is True
    finally:
        settings.ENABLE_UNDERSTANDING = old


def test_understanding_agent_mocked_extract_and_ground():
    llm_json = """{
      "entities": [
        {"id": "e1", "type": "Org", "name": "Acme",
         "aliases": [], "evidence": [{"chunk_id": "doc_0", "quote": "Acme Corp"}]},
        {"id": "e2", "type": "Org", "name": "Ghost",
         "aliases": [], "evidence": [{"chunk_id": "doc_0", "quote": "not in text"}]}
      ],
      "concepts": [],
      "events": [],
      "topics": [{"id": "t1", "label": "Policy", "chunk_ids": ["doc_0"]}],
      "citations": [],
      "relations": [{"id": "r1", "src": "e1", "rel": "RELATES_TO", "dst": "e2", "confidence": 0.5, "evidence": []}]
    }"""
    old = settings.ENABLE_UNDERSTANDING
    settings.ENABLE_UNDERSTANDING = True
    try:
        with patch("src.agents.models.get_nim_client", return_value=object()):
            with patch(
                "src.agents.models.call_chat_with_fallback",
                return_value=(llm_json, "mock-light"),
            ):
                result = UnderstandingAgent().extract(
                    "doc",
                    [{"chunk_id": "doc_0", "text": "Acme Corp announced a policy."}],
                    routing_decision={
                        "selected_model": "mock-light",
                        "fallbacks": ["mock-light"],
                        "tier": "light",
                    },
                )
        assert isinstance(result, UnderstandingResult)
        assert result.model_used == "mock-light"
        assert len(result.document.entities) == 1
        assert result.document.entities[0].id == "e1"
        assert result.document.entities[0].evidence[0].chunk_id == "doc_0"
        assert result.document.entities[0].evidence[0].quote
        # relation dropped because e2 ungrounded
        assert len(result.document.relations) == 0
        assert len(result.document.topics) == 1
    finally:
        settings.ENABLE_UNDERSTANDING = old


def test_config_flags():
    assert hasattr(settings, "ENABLE_UNDERSTANDING")
    assert hasattr(settings, "UNDERSTANDING_MAX_CHUNKS_PER_CALL")


if __name__ == "__main__":
    test_extract_json_object_plain()
    test_extract_json_object_fenced_and_trailing_comma()
    test_extract_json_object_invalid()
    test_quote_grounded_substring()
    test_grounding_drops_ungrounded_entities()
    test_knowledge_from_extraction()
    test_enable_understanding_false_skips_llm()
    test_understanding_agent_mocked_extract_and_ground()
    test_config_flags()
    print("All Phase 2.F understanding tests passed.")
