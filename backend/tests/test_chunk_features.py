"""Unit tests for per-chunk feature extraction."""
from src.agents.chunk_features import extract_chunk_features


class C:
    def __init__(self, content, **kw):
        self.content = content
        self.chunk_kind = kw.get("chunk_kind", "text")
        self.section_path = kw.get("section_path", "Methods")
        self.parent_id = kw.get("parent_id", "p1")


def test_extract_chunk_features_basic():
    chunks = [
        C("Simple appendix note about references and definitions. " * 5, section_path="Appendix"),
        C(
            "The theorem states that the gradient of the loss with respect to "
            "the covariance matrix yields an optimizer update. $E=mc^2$ "
            "algorithm latency throughput. " * 8,
            section_path="Methods/Math",
        ),
        C("| a | b |\n|---|---|\n| 1 | 2 |", chunk_kind="table", section_path="Results"),
    ]
    feats = extract_chunk_features(chunks)
    assert len(feats) == 3
    assert feats[0]["token_count"] > 0
    assert "complexity" in feats[0]
    assert "importance" in feats[0]
    assert feats[1]["equation_count"] >= 1
    assert feats[1]["complexity"] > feats[0]["complexity"]
    assert feats[2]["section_type"] == "table"
