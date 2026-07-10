"""Phase 2.C — ContextAssembler unit tests (no NIM required)."""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.context.assembler import (
    ContextAssembler,
    ContextPack,
    assemble_context,
    budget_for_tier,
    _lexical_overlap,
)
from src.chunking.service import estimate_tokens
from src.core.config import settings
from src.retrieval.service import RetrievedPassage


def _p(cid, content, score=0.0, rank=0, parent_id=None, section_path=None):
    return RetrievedPassage(
        chunk_id=cid,
        content=content,
        score=score,
        rank=rank,
        parent_id=parent_id,
        section_path=section_path,
    )


def test_dedupe_near_duplicates():
    a = "The carbon intensity of the regional power grid is elevated during peak hours."
    b = "The carbon intensity of the regional power grid is elevated during peak hours!"
    # High lexical overlap
    assert _lexical_overlap(a, b) >= 0.92
    pack = ContextAssembler(dedup_threshold=0.92, token_budget=5000).pack(
        [
            _p("1", a, score=0.9, rank=0),
            _p("2", b, score=0.5, rank=1),
            _p("3", "Completely unrelated recipe for chocolate cake frosting.", score=0.1, rank=2),
        ]
    )
    assert pack.stats["after_dedupe"] == 2
    assert "1" in pack.provenance
    assert "2" not in pack.provenance  # lower-score duplicate dropped
    assert "3" in pack.provenance


def test_token_budget_respected():
    long = "word " * 400  # ~500 tokens each roughly (word+space = 5 chars → ~1 token each via //4)
    passages = [
        _p(f"c{i}", long + f" unique_marker_{i}", score=1.0 - i * 0.1, rank=i)
        for i in range(8)
    ]
    budget = 300
    pack = ContextAssembler(token_budget=budget).pack(passages)
    assert pack.tokens_used <= budget + 50  # small formatting slack
    assert pack.stats["packed"] < 8
    assert pack.stats["packed"] >= 1


def test_sibling_merge_same_parent():
    pack = ContextAssembler(token_budget=5000).pack(
        [
            _p("a", "First sibling about emissions.", score=0.8, rank=0, parent_id="p1", section_path="1/Intro"),
            _p("b", "Second sibling about intensity.", score=0.7, rank=1, parent_id="p1", section_path="1/Intro"),
            _p("c", "Other section text.", score=0.6, rank=2, parent_id="p2", section_path="2/Body"),
        ]
    )
    # a+b merged → 2 packed blocks
    assert pack.stats["after_merge"] == 2
    assert pack.stats["packed"] == 2
    merged = next(p for p in pack.passages if "a" in p.chunk_ids)
    assert "b" in merged.chunk_ids
    assert "First sibling" in merged.content and "Second sibling" in merged.content


def test_section_order_in_context():
    pack = ContextAssembler(token_budget=5000).pack(
        [
            _p("z", "Later section content here.", score=0.99, rank=0, section_path="2/B"),
            _p("y", "Earlier section content here.", score=0.5, rank=1, section_path="1/A"),
        ]
    )
    # Higher score selected both; section order puts 1/A before 2/B
    assert pack.context_text.index("Earlier") < pack.context_text.index("Later")
    assert "[1]" in pack.context_text and "[2]" in pack.context_text


def test_provenance_retains_chunk_id_and_rank():
    pack = assemble_context(
        [_p("doc_0", "Alpha evidence passage about grids.", score=0.88, rank=3, parent_id="p", section_path="S1")]
    )
    assert "doc_0" in pack.provenance
    entry = pack.provenance["doc_0"]
    assert entry.rank == 3
    assert entry.score == 0.88
    assert entry.parent_id == "p"
    assert entry.citation == 1


def test_source_texts_compatible():
    pack = assemble_context([_p("1", "Source text A.", score=1.0), _p("2", "Source text B.", score=0.5)])
    assert isinstance(pack.source_texts, list)
    assert all(isinstance(s, str) for s in pack.source_texts)
    assert len(pack.source_texts) == pack.stats["packed"]


def test_budget_for_tier():
    assert budget_for_tier("light") == settings.CONTEXT_TOKEN_BUDGET_LIGHT
    assert budget_for_tier("medium") == settings.CONTEXT_TOKEN_BUDGET_MEDIUM
    assert budget_for_tier("heavy") == settings.CONTEXT_TOKEN_BUDGET_HEAVY
    assert budget_for_tier(None) == settings.CONTEXT_TOKEN_BUDGET_HEAVY


def test_config_flags():
    assert hasattr(settings, "USE_CONTEXT_ASSEMBLER")
    assert hasattr(settings, "CONTEXT_DEDUP_THRESHOLD")
    assert settings.CONTEXT_DEDUP_THRESHOLD == 0.92


def test_empty_input():
    pack = ContextAssembler().pack([])
    assert pack.context_text == ""
    assert pack.passages == []
    assert isinstance(pack, ContextPack)


if __name__ == "__main__":
    test_dedupe_near_duplicates()
    test_token_budget_respected()
    test_sibling_merge_same_parent()
    test_section_order_in_context()
    test_provenance_retains_chunk_id_and_rank()
    test_source_texts_compatible()
    test_budget_for_tier()
    test_config_flags()
    test_empty_input()
    print("All Phase 2.C context assembler tests passed.")
