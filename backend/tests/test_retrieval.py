"""Phase 2.B — Hybrid retrieval unit tests (no NIM required)."""
import sys
import os
import tempfile
import shutil

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.retrieval.rrf import reciprocal_rank_fusion
from src.retrieval.bm25 import BM25Index, tokenize, build_and_save, load_index, delete_index
from src.memory import embedding_cache
from src.core.config import settings


def test_rrf_basic():
    a = ["d1", "d2", "d3"]
    b = ["d2", "d4", "d1"]
    fused = reciprocal_rank_fusion([a, b], k=60)
    ids = [doc_id for doc_id, _ in fused]
    # d1 and d2 appear in both lists → should rank above unique-only docs
    assert ids[0] in ("d1", "d2")
    assert "d2" in ids[:2]
    assert set(ids) == {"d1", "d2", "d3", "d4"}


def test_rrf_top_n():
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["c", "a"]], k=60, top_n=2)
    assert len(fused) == 2


def test_rrf_empty():
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []


def test_bm25_tokenize():
    assert "hello" in tokenize("Hello, World_42!")
    assert "world_42" in tokenize("Hello, World_42!")


def test_bm25_search_prefers_term_overlap():
    idx = BM25Index()
    idx.build(
        [
            ("c1", "The carbon intensity of the grid is high today."),
            ("c2", "Recipe for chocolate cake with frosting."),
            ("c3", "Grid carbon emissions and intensity metrics."),
        ]
    )
    hits = idx.search("carbon grid intensity", k=2)
    assert len(hits) == 2
    assert hits[0][0] in ("c1", "c3")
    assert hits[1][0] in ("c1", "c3")


def test_bm25_persist_roundtrip():
    root = tempfile.mkdtemp()
    try:
        old = settings.VECTOR_DB_PATH
        settings.VECTOR_DB_PATH = root
        docs = [("a", "alpha beta gamma"), ("b", "delta epsilon")]
        build_and_save("doc-xyz", docs)
        loaded = load_index("doc-xyz")
        assert loaded is not None
        assert loaded.N == 2
        hits = loaded.search("alpha gamma", k=1)
        assert hits[0][0] == "a"
        delete_index("doc-xyz")
        assert load_index("doc-xyz") is None
    finally:
        settings.VECTOR_DB_PATH = old
        shutil.rmtree(root, ignore_errors=True)


def test_embedding_cache_roundtrip():
    root = tempfile.mkdtemp()
    try:
        old = settings.VECTOR_DB_PATH
        settings.VECTOR_DB_PATH = root
        embedding_cache.reset_stats()
        model = "test-model"
        text = "hello cache"
        assert embedding_cache.get_cached(model, text) is None
        embedding_cache.put_cached(model, text, [0.1, 0.2, 0.3])
        got = embedding_cache.get_cached(model, text)
        assert got == [0.1, 0.2, 0.3]
        # second get is a hit
        embedding_cache.get_cached(model, text)
        st = embedding_cache.stats()
        assert st["hits"] >= 2
        assert st["misses"] >= 1

        vecs, misses = embedding_cache.get_many(model, [text, "missing"])
        assert vecs[0] == [0.1, 0.2, 0.3]
        assert misses == [1]
        embedding_cache.put_many(model, ["missing"], [[9.0]])
        vecs2, misses2 = embedding_cache.get_many(model, [text, "missing"])
        assert misses2 == []
        assert vecs2[1] == [9.0]
    finally:
        settings.VECTOR_DB_PATH = old
        shutil.rmtree(root, ignore_errors=True)


def test_config_flags_present():
    assert hasattr(settings, "ENABLE_HYBRID_RETRIEVAL")
    assert hasattr(settings, "ENABLE_EMBEDDING_CACHE")
    assert hasattr(settings, "RAG_DENSE_K")
    assert hasattr(settings, "RAG_SPARSE_K")
    assert hasattr(settings, "RAG_RRF_K")
    assert hasattr(settings, "RAG_RERANK_N")
    assert hasattr(settings, "ENABLE_PARENT_EXPAND")
    assert hasattr(settings, "RAG_PARENT_EXPAND_MAX")


if __name__ == "__main__":
    test_rrf_basic()
    test_rrf_top_n()
    test_rrf_empty()
    test_bm25_tokenize()
    test_bm25_search_prefers_term_overlap()
    test_bm25_persist_roundtrip()
    test_embedding_cache_roundtrip()
    test_config_flags_present()
    print("All Phase 2.B retrieval tests passed.")
