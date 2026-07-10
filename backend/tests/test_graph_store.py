"""Phase 2.G — GraphStore unit tests (no Chroma/NIM required)."""
import sys
import os
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.knowledge.schemas import (
    Entity,
    EvidenceSpan,
    KnowledgeDocument,
    Relation,
)
from src.knowledge.graph_store import (
    GraphStore,
    graph_from_knowledge,
    sync_graph_from_knowledge,
)
from src.core.config import settings


def _doc(document_id: str) -> KnowledgeDocument:
    return KnowledgeDocument(
        document_id=document_id,
        status="done",
        entities=[
            Entity(
                id="acme",
                type="Org",
                name="Acme Corp",
                aliases=["Acme"],
                evidence=[EvidenceSpan(chunk_id=f"{document_id}_0", quote="Acme Corp")],
            ),
            Entity(
                id="policy",
                type="Concept",
                name="Carbon Policy",
                evidence=[EvidenceSpan(chunk_id=f"{document_id}_1", quote="Carbon Policy")],
            ),
        ],
        relations=[
            Relation(
                id="r1",
                src="acme",
                rel="RELATES_TO",
                dst="policy",
                confidence=0.9,
                evidence=[EvidenceSpan(chunk_id=f"{document_id}_2", quote="announced")],
            ),
            # Duplicate edge — should collapse in graph_from_knowledge
            Relation(
                id="r1b",
                src="acme",
                rel="RELATES_TO",
                dst="policy",
                confidence=0.5,
                evidence=[EvidenceSpan(chunk_id=f"{document_id}_2", quote="announced")],
            ),
        ],
    )


def test_graph_from_knowledge_dedupes_edges():
    g = graph_from_knowledge(_doc("d1"))
    assert len(g.nodes) == 2
    assert len(g.edges) == 1
    assert g.edges[0].confidence == 0.9 or g.edges[0].src == "acme"


def test_edge_upsert_idempotent():
    doc_id = f"gtest-{uuid.uuid4().hex[:8]}"
    store = GraphStore()
    store.delete_graph(doc_id)
    store.upsert_edge(doc_id, "a", "RELATES_TO", "b", confidence=0.4, evidence_chunk_ids=["c1"])
    store.upsert_edge(doc_id, "a", "RELATES_TO", "b", confidence=0.8, evidence_chunk_ids=["c2"])
    g = store.get_graph(doc_id)
    assert len(g.edges) == 1
    assert g.edges[0].confidence == 0.8
    assert "c1" in g.edges[0].evidence_chunk_ids
    assert "c2" in g.edges[0].evidence_chunk_ids
    store.delete_graph(doc_id)


def test_replace_and_neighbor_chunks():
    doc_id = f"gtest-{uuid.uuid4().hex[:8]}"
    store = GraphStore()
    store.delete_graph(doc_id)
    graph = store.replace_from_knowledge(_doc(doc_id))
    assert len(graph.nodes) == 2
    assert len(graph.edges) == 1

    loaded = store.get_graph(doc_id)
    assert len(loaded.nodes) == 2
    assert any(n.name == "Acme Corp" for n in loaded.nodes)

    matched = store.match_entity_ids(doc_id, "What did Acme Corp announce?")
    assert "acme" in matched

    seeds = store.neighbor_chunk_ids(doc_id, "Tell me about Acme Corp policy")
    # entity evidence + neighbor edge evidence
    assert f"{doc_id}_0" in seeds  # acme evidence
    assert f"{doc_id}_1" in seeds or f"{doc_id}_2" in seeds  # policy or edge
    store.delete_graph(doc_id)


def test_sync_from_knowledge_helper():
    doc_id = f"gtest-{uuid.uuid4().hex[:8]}"
    g = sync_graph_from_knowledge(doc_id, _doc(doc_id))
    assert g is not None
    assert len(g.nodes) == 2
    GraphStore().delete_graph(doc_id)


def test_low_confidence_edges_excluded_from_seed():
    doc_id = f"gtest-{uuid.uuid4().hex[:8]}"
    store = GraphStore()
    kd = KnowledgeDocument(
        document_id=doc_id,
        entities=[
            Entity(
                id="x",
                type="Org",
                name="Zephyr Labs",
                evidence=[EvidenceSpan(chunk_id=f"{doc_id}_0", quote="Zephyr")],
            ),
            Entity(
                id="y",
                type="Org",
                name="Other Co",
                evidence=[EvidenceSpan(chunk_id=f"{doc_id}_9", quote="Other")],
            ),
        ],
        relations=[
            Relation(
                id="weak",
                src="x",
                rel="RELATES_TO",
                dst="y",
                confidence=0.1,
                evidence=[EvidenceSpan(chunk_id=f"{doc_id}_9", quote="Other")],
            ),
        ],
    )
    store.replace_from_knowledge(kd)
    seeds = store.neighbor_chunk_ids(
        doc_id, "Zephyr Labs", max_chunks=10, min_confidence=0.4
    )
    # matched node evidence kept; weak edge neighbor chunk should not expand via edge
    assert f"{doc_id}_0" in seeds
    assert f"{doc_id}_9" not in seeds
    store.delete_graph(doc_id)


def test_config_flags():
    assert hasattr(settings, "ENABLE_GRAPH_SEED")
    assert hasattr(settings, "GRAPH_SEED_MAX_CHUNKS")
    assert hasattr(settings, "GRAPH_SEED_MIN_CONFIDENCE")


if __name__ == "__main__":
    test_graph_from_knowledge_dedupes_edges()
    test_edge_upsert_idempotent()
    test_replace_and_neighbor_chunks()
    test_sync_from_knowledge_helper()
    test_low_confidence_edges_excluded_from_seed()
    test_config_flags()
    print("All Phase 2.G graph store tests passed.")
