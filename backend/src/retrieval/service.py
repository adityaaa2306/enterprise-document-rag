"""
RetrievalService — hybrid dense + BM25 → RRF → NIM rerank → parent expand (Phase 2.B).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.core.config import settings
from src.agents import models
from src.retrieval.bm25 import load_index, build_and_save
from src.retrieval.rrf import reciprocal_rank_fusion

log = logging.getLogger(__name__)


def _storage():
    from src.memory import storage

    return storage


@dataclass
class RetrievedPassage:
    chunk_id: str
    content: str
    score: float = 0.0
    rank: int = 0
    parent_id: Optional[str] = None
    section_path: Optional[str] = None
    source: str = "hybrid"  # dense|sparse|rrf|rerank|parent_expand


@dataclass
class RetrievalResult:
    passages: List[RetrievedPassage] = field(default_factory=list)
    debug: Dict[str, Any] = field(default_factory=dict)


class _ContentChunk:
    def __init__(self, content: str, chunk_id: str = "", meta: Optional[dict] = None):
        self.content = content
        self.chunk_id = chunk_id
        self.meta = meta or {}


class RetrievalService:
    def search(
        self,
        query: str,
        document_id: str,
        top_k: Optional[int] = None,
        graph_seed: Optional[bool] = None,
    ) -> RetrievalResult:
        top_k = top_k if top_k is not None else settings.RAG_TOP_K
        use_seed = settings.ENABLE_GRAPH_SEED if graph_seed is None else bool(graph_seed)

        if not settings.ENABLE_HYBRID_RETRIEVAL:
            return self._dense_only(query, document_id, top_k, graph_seed=use_seed)

        dense_k = settings.RAG_DENSE_K
        sparse_k = settings.RAG_SPARSE_K
        rrf_k = settings.RAG_RRF_K
        rerank_n = settings.RAG_RERANK_N

        dense_ids, dense_map = self._dense_search(query, document_id, dense_k)
        sparse_ids, sparse_map = self._sparse_search(query, document_id, sparse_k)

        seed_ids: List[str] = []
        seed_map: Dict[str, str] = {}
        if use_seed:
            seed_ids, seed_map = self._graph_seed(query, document_id)

        ranked_lists = [dense_ids, sparse_ids]
        if seed_ids:
            ranked_lists.append(seed_ids)

        fused = reciprocal_rank_fusion(ranked_lists, k=60, top_n=rrf_k)
        fused_ids = [doc_id for doc_id, _ in fused]

        # Build candidate passages (prefer text from either map)
        candidates: List[RetrievedPassage] = []
        for i, (doc_id, score) in enumerate(fused):
            text = dense_map.get(doc_id) or sparse_map.get(doc_id) or seed_map.get(doc_id) or ""
            if not text:
                continue
            meta = self._meta_for(document_id, doc_id)
            src = "graph_seed" if doc_id in seed_ids and doc_id not in dense_ids and doc_id not in sparse_ids else "rrf"
            candidates.append(
                RetrievedPassage(
                    chunk_id=doc_id,
                    content=text,
                    score=score,
                    rank=i,
                    parent_id=meta.get("parent_id"),
                    section_path=meta.get("section_path"),
                    source=src,
                )
            )

        if not candidates:
            # Fall back to dense-only if BM25 missing / empty
            log.warning("Hybrid fusion empty; falling back to dense-only")
            return self._dense_only(query, document_id, top_k, graph_seed=use_seed)

        # Rerank top fused
        to_rerank = candidates[: max(rerank_n, top_k)]
        passages_text = [c.content for c in to_rerank]
        reranked_texts = models.rerank(query, passages_text, top_k=min(top_k, len(passages_text)))

        # Map back preserving first occurrence
        by_text = {}
        for c in to_rerank:
            by_text.setdefault(c.content, c)

        ranked: List[RetrievedPassage] = []
        used = set()
        for i, text in enumerate(reranked_texts):
            base = by_text.get(text)
            if not base or base.chunk_id in used:
                # duplicate text — skip
                continue
            used.add(base.chunk_id)
            ranked.append(
                RetrievedPassage(
                    chunk_id=base.chunk_id,
                    content=base.content,
                    score=base.score,
                    rank=i,
                    parent_id=base.parent_id,
                    section_path=base.section_path,
                    source="rerank",
                )
            )

        if settings.ENABLE_PARENT_EXPAND:
            ranked = self._parent_expand(document_id, ranked, max_extra=settings.RAG_PARENT_EXPAND_MAX)

        limit = top_k + (settings.RAG_PARENT_EXPAND_MAX if settings.ENABLE_PARENT_EXPAND else 0)
        debug = {
            "mode": "hybrid",
            "dense_ids": dense_ids[:10],
            "sparse_ids": sparse_ids[:10],
            "seed_ids": seed_ids[:10],
            "graph_seed": bool(seed_ids),
            "fused_ids": fused_ids[:10],
            "returned": [p.chunk_id for p in ranked[:limit]],
        }
        return RetrievalResult(passages=ranked[:limit], debug=debug)

    def _graph_seed(
        self, query: str, document_id: str
    ) -> tuple[List[str], Dict[str, str]]:
        """Return (ordered chunk ids, id→text) from graph neighborhood."""
        try:
            from src.knowledge.graph_store import GraphStore

            store = GraphStore()
            seed_ids = store.neighbor_chunk_ids(document_id, query)
            if not seed_ids:
                return [], {}
            storage = _storage()
            rows = storage.retrieve_chunks(document_id)
            by_id = {f"{document_id}_{r['index']}": r["text"] for r in rows}
            # Also allow exact chunk ids stored in evidence
            id_to_text: Dict[str, str] = {}
            ordered: List[str] = []
            for cid in seed_ids:
                text = by_id.get(cid, "")
                if not text:
                    # try loading from ChunkModel directly
                    try:
                        db = storage.DBSessionLocal()
                        row = db.get(storage.ChunkModel, cid)
                        db.close()
                        if row and row.text:
                            text = row.text
                    except Exception:
                        text = ""
                if text:
                    id_to_text[cid] = text
                    ordered.append(cid)
            return ordered, id_to_text
        except Exception as e:
            log.warning(f"Graph seed failed: {e}")
            return [], {}

    def _dense_only(
        self,
        query: str,
        document_id: str,
        top_k: int,
        graph_seed: bool = False,
    ) -> RetrievalResult:
        ids, id_to_text = self._dense_search(query, document_id, max(top_k, settings.RAG_CANDIDATE_K))
        seed_ids: List[str] = []
        if graph_seed and settings.ENABLE_GRAPH_SEED:
            seed_ids, seed_map = self._graph_seed(query, document_id)
            for cid in seed_ids:
                if cid not in id_to_text and cid in seed_map:
                    id_to_text[cid] = seed_map[cid]
                    ids = [cid] + [i for i in ids if i != cid]

        if not ids:
            return RetrievalResult(
                passages=[],
                debug={"mode": "dense_only", "empty": True, "seed_ids": seed_ids},
            )

        texts = [id_to_text[i] for i in ids if i in id_to_text]
        id_by_text = {id_to_text[i]: i for i in ids if i in id_to_text}
        reranked = models.rerank(query, texts, top_k=top_k)
        passages = []
        for i, text in enumerate(reranked):
            cid = id_by_text.get(text, f"unknown_{i}")
            meta = self._meta_for(document_id, cid)
            passages.append(
                RetrievedPassage(
                    chunk_id=cid,
                    content=text,
                    rank=i,
                    parent_id=meta.get("parent_id"),
                    section_path=meta.get("section_path"),
                    source="dense_rerank",
                )
            )
        if settings.ENABLE_PARENT_EXPAND:
            passages = self._parent_expand(document_id, passages, max_extra=settings.RAG_PARENT_EXPAND_MAX)
        return RetrievalResult(
            passages=passages,
            debug={"mode": "dense_only", "seed_ids": seed_ids[:10], "graph_seed": bool(seed_ids)},
        )

    def _dense_search(
        self, query: str, document_id: str, k: int
    ) -> tuple[List[str], Dict[str, str]]:
        collection = _storage()._get_documents_collection()
        if not models.get_embedding_model():
            return [], {}
        try:
            qvec = models.embed_texts([query])[0]
            results = collection.query(
                query_embeddings=[qvec],
                n_results=k,
                where={"document_id": document_id},
                include=["documents", "metadatas"],
            )
        except Exception as e:
            log.error(f"Dense search failed: {e}")
            return [], {}

        ids = (results.get("ids") or [[]])[0]
        docs = (results.get("documents") or [[]])[0]
        id_to_text = {i: t for i, t in zip(ids, docs) if t}
        return list(ids), id_to_text

    def _sparse_search(
        self, query: str, document_id: str, k: int
    ) -> tuple[List[str], Dict[str, str]]:
        storage = _storage()
        idx = load_index(document_id)
        if idx is None:
            # Build from SQLite if missing
            rows = storage.retrieve_chunks(document_id)
            if not rows:
                return [], {}
            docs = [(f"{document_id}_{r['index']}", r["text"]) for r in rows]
            idx = build_and_save(document_id, docs)

        hits = idx.search(query, k=k)
        id_to_text: Dict[str, str] = {}
        # Load texts from SQLite
        rows = storage.retrieve_chunks(document_id)
        by_id = {f"{document_id}_{r['index']}": r["text"] for r in rows}
        # Also map raw index keys if stored that way
        for cid, _score in hits:
            id_to_text[cid] = by_id.get(cid, "")
        # Fill missing from index order using retrieve
        ids = [cid for cid, _ in hits if id_to_text.get(cid)]
        return ids, {i: id_to_text[i] for i in ids}

    def _meta_for(self, document_id: str, chunk_id: str) -> Dict[str, Any]:
        try:
            storage = _storage()
            db = storage.DBSessionLocal()
            row = db.get(storage.ChunkModel, chunk_id)
            db.close()
            if not row:
                return {}
            return {
                "parent_id": row.parent_id,
                "section_path": row.section_path,
                "chunk_kind": row.chunk_kind,
            }
        except Exception:
            return {}

    def _parent_expand(
        self,
        document_id: str,
        passages: List[RetrievedPassage],
        max_extra: int = 3,
    ) -> List[RetrievedPassage]:
        """Attach sibling/parent-section context for hit children (capped)."""
        if not passages or max_extra <= 0:
            return passages

        existing = {p.chunk_id for p in passages}
        parent_ids = [p.parent_id for p in passages if p.parent_id]
        if not parent_ids:
            return passages

        try:
            storage = _storage()
            db = storage.DBSessionLocal()
            extras: List[RetrievedPassage] = []
            for pid in dict.fromkeys(parent_ids):  # unique, order-preserving
                if len(extras) >= max_extra:
                    break
                siblings = (
                    db.query(storage.ChunkModel)
                    .filter(
                        storage.ChunkModel.document_id == document_id,
                        storage.ChunkModel.parent_id == pid,
                    )
                    .all()
                )
                # Prefer a title/merged section overview: shortest non-hit sibling or first
                for sib in siblings:
                    if sib.id in existing:
                        continue
                    extras.append(
                        RetrievedPassage(
                            chunk_id=sib.id,
                            content=sib.text or "",
                            score=0.0,
                            rank=len(passages) + len(extras),
                            parent_id=sib.parent_id,
                            section_path=sib.section_path,
                            source="parent_expand",
                        )
                    )
                    existing.add(sib.id)
                    break
            db.close()
            return passages + extras
        except Exception as e:
            log.warning(f"Parent expand failed: {e}")
            return passages


def search_as_content_chunks(
    query: str, document_id: str, k: Optional[int] = None
) -> List[Any]:
    """Adapter returning objects with ``.content`` for legacy RAG callers."""
    result = RetrievalService().search(query, document_id, top_k=k)
    return [_ContentChunk(p.content, p.chunk_id, {"score": p.score, "source": p.source}) for p in result.passages]
