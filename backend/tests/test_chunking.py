"""Phase 2.A — ChunkingService unit tests (no NIM / unstructured required)."""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.chunking import ChunkingService, AdaptiveChunk, estimate_tokens
from src.chunking.service import _lexical_overlap
from src.core.config import settings


class _El:
    def __init__(self, type: str, content: str):
        self.type = type
        self.content = content


def test_estimate_tokens():
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a" * 40) == 10


def test_tables_remain_atomic():
    elements = [
        _El("Title", "Section A"),
        _El("Text", "Intro paragraph about cats and dogs living together."),
        _El("Table", "--- TABLE START ---\nA|B\n1|2\n--- TABLE END ---"),
        _El("Text", "After table commentary continues here with more words."),
    ]
    chunks, parents, meta = ChunkingService(max_tokens=200, sim_threshold=0.0).build(
        elements, document_id="doc1"
    )
    table_chunks = [c for c in chunks if c.chunk_kind == "table" or c.type == "Table"]
    assert len(table_chunks) == 1
    assert "TABLE START" in table_chunks[0].content
    # Table content should not be merged into neighboring text
    for c in chunks:
        if c.type == "Text" or c.chunk_kind == "merged":
            assert "TABLE START" not in c.content
    assert meta["adaptive"] is True
    assert meta["table_chunks"] == 1


def test_title_creates_section_parents():
    elements = [
        _El("Title", "Introduction"),
        _El("Text", "First body under introduction with enough tokens here."),
        _El("Title", "Methods"),
        _El("Text", "Second body under methods with enough tokens here too."),
    ]
    chunks, parents, meta = ChunkingService(
        max_tokens=500, sim_threshold=0.0, title_as_chunk=True
    ).build(elements, document_id="doc2")
    assert meta["section_count"] >= 2
    titles = {p.title for p in parents}
    assert "Introduction" in titles
    assert "Methods" in titles
    # Children point at parents
    assert any(c.section_path == "Introduction" for c in chunks)
    assert any(c.section_path == "Methods" for c in chunks)


def test_token_budget_splits_long_section():
    long_a = "alpha " * 200  # ~300 tokens-ish
    long_b = "beta " * 200
    elements = [
        _El("Title", "Long"),
        _El("Text", long_a),
        _El("Text", long_b),
    ]
    chunks, parents, meta = ChunkingService(max_tokens=100, sim_threshold=0.0).build(
        elements, document_id="doc3"
    )
    # Title + at least 2 body chunks due to budget
    body = [c for c in chunks if c.type != "Title"]
    assert len(body) >= 2


def test_similarity_split_with_lexical_fallback():
    elements = [
        _El("Title", "Topics"),
        _El("Text", "Quantum entanglement photon polarization experiment results. " * 40),
        _El("Text", "Chocolate cake recipe flour sugar butter oven temperature. " * 40),
    ]
    # High threshold + low min fill → force split on low overlap once buffer is full enough
    chunks, _, _ = ChunkingService(
        max_tokens=2000,
        sim_threshold=0.5,
        min_tokens_before_sim_split=50,
        title_as_chunk=True,
    ).build(elements, document_id="doc4")
    body = [c for c in chunks if c.type != "Title"]
    assert len(body) >= 2
    assert _lexical_overlap(body[0].content, body[1].content) < 0.5


def test_tiny_elements_do_not_explode_chunk_count():
    """Regression: unstructured can emit thousands of short fragments."""
    elements = [_El("Text", f"Short fragment number {i} about topic alpha.") for i in range(3000)]
    chunks, _, meta = ChunkingService(max_tokens=800, max_chunk_count=48).build(
        elements, document_id="doc-explosion"
    )
    assert len(chunks) <= 48
    assert meta["chunk_count"] <= 48
    assert meta["raw_chunk_count"] >= meta["chunk_count"]
    assert all(c.content.strip() for c in chunks)


def test_titles_fold_into_body_by_default():
    elements = [
        _El("Title", "Introduction"),
        _El("Text", "First body under introduction with enough tokens here."),
    ]
    chunks, parents, _ = ChunkingService(max_tokens=500, sim_threshold=0.0).build(
        elements, document_id="doc-title-fold"
    )
    assert any(p.title == "Introduction" for p in parents)
    assert not any(c.type == "Title" for c in chunks)
    assert any("Introduction" in c.content for c in chunks)


def test_adaptive_chunk_has_content_for_downstream():
    elements = [_El("Text", "Hello world content for summarizers.")]
    chunks, _, _ = ChunkingService().build(elements, document_id="doc5")
    assert len(chunks) == 1
    assert isinstance(chunks[0], AdaptiveChunk)
    assert chunks[0].content.startswith("Hello")
    assert chunks[0].document_id == "doc5"
    assert chunks[0].parent_id is not None


def test_flag_defaults():
    assert hasattr(settings, "USE_ADAPTIVE_CHUNKING")
    assert hasattr(settings, "CHUNK_MAX_TOKENS")
    assert hasattr(settings, "CHUNK_SIM_THRESHOLD")
    assert hasattr(settings, "CHUNK_MAX_COUNT")
    assert settings.CHUNK_MAX_COUNT >= 512
    assert settings.CHUNK_MAX_TOKENS >= 512


if __name__ == "__main__":
    test_estimate_tokens()
    test_tables_remain_atomic()
    test_title_creates_section_parents()
    test_token_budget_splits_long_section()
    test_similarity_split_with_lexical_fallback()
    test_adaptive_chunk_has_content_for_downstream()
    test_flag_defaults()
    print("ALL Phase 2.A TESTS PASSED")
