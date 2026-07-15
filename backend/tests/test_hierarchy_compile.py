"""Hierarchy + medium-first compile chain tests."""
from src.agents.models import _compile_model_chains
from src.core.hierarchy import (
    build_hierarchy_levels,
    group_summaries_by_section,
    group_summaries_adaptive,
)


class C:
    def __init__(self, content, parent_id, section_path):
        self.content = content
        self.parent_id = parent_id
        self.section_path = section_path


def test_group_and_hierarchy_levels():
    chunks = [
        C("a", "p1", "Intro"),
        C("b", "p1", "Intro"),
        C("c", "p2", "Methods"),
        C("d", "p2", "Methods"),
        C("e", "p3", "Results"),
    ]
    summaries = ["s1", "s2", "s3", "s4", "s5"]
    groups = group_summaries_by_section(chunks, summaries)
    assert len(groups) == 3
    levels = build_hierarchy_levels(chunks, summaries, fan_in=2)
    assert levels[0]["kind"] == "chunk"
    assert levels[1]["kind"] == "regional"
    assert levels[1]["nodes"]


def test_adaptive_compresses_unique_section_parents():
    """Unique parent_id per chunk must not force 1:1 regionals."""
    chunks = [
        C(f"content about rag systems and carbon routing number {i} " * 8, f"sec-{i}", f"S{i}")
        for i in range(12)
    ]
    summaries = [
        f"Summary of rag and carbon topic {i} with overlapping vocabulary for continuity."
        for i in range(12)
    ]
    naive = group_summaries_by_section(chunks, summaries)
    adaptive, diag = group_summaries_adaptive(chunks, summaries, capability_score=0.6)
    assert len(naive) == 12
    assert len(adaptive) < len(naive), f"expected compression, got {len(adaptive)} regionals"
    assert diag["compression_ratio"] > 1.0
    assert diag["regional_count"] == len(adaptive)
    levels = build_hierarchy_levels(chunks, summaries, fan_in=4, adaptive_regional=True)
    regional = next(lv for lv in levels if lv["kind"] == "regional")
    assert len(regional["nodes"]) < 12


def test_compile_chains_medium_first():
    chains = _compile_model_chains(None, medium_first=True)
    assert chains
    # First chain should be medium models when medium_first
    from src.core.config import settings

    med = settings.medium_models()[0]
    assert chains[0][0] == med or med in chains[0]
    # Deduped + capped — no repeated model ids across the ladder
    flat = [m for c in chains for m in c]
    assert len(flat) == len(set(flat))
    assert len(flat) <= 3
