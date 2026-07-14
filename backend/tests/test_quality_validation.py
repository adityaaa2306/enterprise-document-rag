"""Unit tests for enhanced quality validation."""
from src.agents.quality_validation import validate_pair, validate_chunks


def test_validate_pair_passes_grounded_summary():
    source = (
        "The neural network optimizer reduces latency and improves throughput "
        "for transformer embeddings in production systems."
    )
    summary = "The neural network optimizer improves throughput and reduces latency."
    v = validate_pair(source, summary)
    assert v.coverage > 0.3
    assert "semantic_similarity" in v.to_dict()
    assert "entity_retention" in v.to_dict()


def test_validate_chunks_reports_failed_indices():
    class C:
        def __init__(self, content):
            self.content = content

    chunks = [C("Alpha beta gamma delta epsilon zeta eta theta.")]
    summaries = ["Completely unrelated fabricated content about zoos and penguins."]
    v = validate_chunks(chunks, summaries)
    assert "failed_indices" in v.details
    assert isinstance(v.details["chunk_confidences"], list)
