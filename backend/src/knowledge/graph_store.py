"""
GraphStore — document knowledge graph persistence + neighbor lookup (Phase 2.G).

Not an agent. Built from grounded KnowledgeDocument; used to seed retrieval.
Uses the shared SQLAlchemy Base/engine (src.db).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from src.core.config import settings
from src.db.models import GraphEdgeModel, GraphNodeModel
from src.db.session import get_session
from src.knowledge.schemas import KnowledgeDocument

log = logging.getLogger(__name__)

# Process-level graph cache (document_id -> DocumentGraph)
_graph_cache: Dict[str, DocumentGraph] = {}
_graph_cache_lock = __import__("threading").RLock()


def invalidate_graph_cache(document_id: Optional[str] = None) -> None:
    with _graph_cache_lock:
        if document_id is None:
            _graph_cache.clear()
        else:
            _graph_cache.pop(document_id, None)


@dataclass
class GraphNode:
    id: str
    type: str
    name: str
    aliases: List[str] = field(default_factory=list)
    evidence_chunk_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "aliases": list(self.aliases),
            "evidence_chunk_ids": list(self.evidence_chunk_ids),
        }


@dataclass
class GraphEdge:
    src: str
    rel: str
    dst: str
    confidence: float = 0.5
    evidence_chunk_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "src": self.src,
            "rel": self.rel,
            "dst": self.dst,
            "confidence": self.confidence,
            "evidence_chunk_ids": list(self.evidence_chunk_ids),
        }


@dataclass
class DocumentGraph:
    document_id: str
    nodes: List[GraphNode] = field(default_factory=list)
    edges: List[GraphEdge] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
        }


def _edge_pk(document_id: str, src: str, rel: str, dst: str) -> str:
    return f"{document_id}::{src}|{rel}|{dst}"


def _node_pk(document_id: str, node_id: str) -> str:
    return f"{document_id}::{node_id}"


def _evidence_chunk_ids(evidence: Sequence[Any]) -> List[str]:
    ids: List[str] = []
    for ev in evidence or []:
        if isinstance(ev, dict):
            cid = ev.get("chunk_id")
        else:
            cid = getattr(ev, "chunk_id", None)
        if cid and str(cid) not in ids:
            ids.append(str(cid))
    return ids


def graph_from_knowledge(doc: KnowledgeDocument) -> DocumentGraph:
    """Build a DocumentGraph from a grounded KnowledgeDocument (idempotent shape)."""
    nodes: Dict[str, GraphNode] = {}

    def _add(nid: str, ntype: str, name: str, aliases: Optional[List[str]], evidence: Sequence[Any]):
        if not nid:
            return
        chunk_ids = _evidence_chunk_ids(evidence)
        if nid in nodes:
            existing = nodes[nid]
            for a in aliases or []:
                if a and a not in existing.aliases:
                    existing.aliases.append(a)
            for c in chunk_ids:
                if c not in existing.evidence_chunk_ids:
                    existing.evidence_chunk_ids.append(c)
            if name and len(name) > len(existing.name):
                existing.name = name
        else:
            nodes[nid] = GraphNode(
                id=nid,
                type=ntype,
                name=name or nid,
                aliases=list(aliases or []),
                evidence_chunk_ids=chunk_ids,
            )

    for e in doc.entities:
        _add(e.id, e.type or "Entity", e.name, e.aliases, e.evidence)
    for c in doc.concepts:
        _add(c.id, "Concept", c.label, [], c.evidence)
    for ev in doc.events:
        _add(ev.id, "Event", ev.name, [], ev.evidence)
    for cit in doc.citations:
        _add(cit.id, "Citation", cit.raw, [], cit.evidence)

    edges: List[GraphEdge] = []
    seen: Set[Tuple[str, str, str]] = set()
    for r in doc.relations:
        key = (r.src, r.rel, r.dst)
        if not r.src or not r.dst or key in seen:
            continue
        seen.add(key)
        edges.append(
            GraphEdge(
                src=r.src,
                rel=r.rel or "RELATES_TO",
                dst=r.dst,
                confidence=float(r.confidence or 0.5),
                evidence_chunk_ids=_evidence_chunk_ids(r.evidence),
            )
        )

    return DocumentGraph(document_id=doc.document_id, nodes=list(nodes.values()), edges=edges)


class GraphStore:
    """Persist / query document knowledge graphs."""

    def __init__(self):
        # Schema is owned by Alembic; no create_all here.
        pass

    def _session(self):
        return get_session()

    def replace_from_knowledge(self, doc: KnowledgeDocument) -> DocumentGraph:
        """Idempotent replace of all nodes/edges for a document from knowledge."""
        graph = graph_from_knowledge(doc)
        self.replace_graph(graph)
        return graph

    def replace_graph(self, graph: DocumentGraph) -> None:
        db = self._session()
        try:
            db.query(GraphNodeModel).filter(GraphNodeModel.document_id == graph.document_id).delete()
            db.query(GraphEdgeModel).filter(GraphEdgeModel.document_id == graph.document_id).delete()

            for n in graph.nodes:
                db.merge(
                    GraphNodeModel(
                        id=_node_pk(graph.document_id, n.id),
                        document_id=graph.document_id,
                        node_id=n.id,
                        node_type=n.type,
                        name=n.name,
                        aliases_json=json.dumps(n.aliases),
                        evidence_json=json.dumps(n.evidence_chunk_ids),
                    )
                )
            for e in graph.edges:
                db.merge(
                    GraphEdgeModel(
                        id=_edge_pk(graph.document_id, e.src, e.rel, e.dst),
                        document_id=graph.document_id,
                        src=e.src,
                        rel=e.rel,
                        dst=e.dst,
                        confidence=e.confidence,
                        evidence_json=json.dumps(e.evidence_chunk_ids),
                    )
                )
            db.commit()
            invalidate_graph_cache(graph.document_id)
            log.info(
                f"GraphStore replaced graph for {graph.document_id}: "
                f"{len(graph.nodes)} nodes, {len(graph.edges)} edges"
            )
        except Exception as e:
            db.rollback()
            log.error(f"GraphStore replace failed: {e}")
            raise
        finally:
            db.close()

    def upsert_edge(
        self,
        document_id: str,
        src: str,
        rel: str,
        dst: str,
        *,
        confidence: float = 0.5,
        evidence_chunk_ids: Optional[List[str]] = None,
    ) -> None:
        """Idempotent single-edge upsert (merge evidence, keep max confidence)."""
        db = self._session()
        try:
            pk = _edge_pk(document_id, src, rel, dst)
            row = db.get(GraphEdgeModel, pk)
            ev = list(evidence_chunk_ids or [])
            if row:
                row.confidence = max(float(row.confidence or 0.0), float(confidence))
                try:
                    existing = json.loads(row.evidence_json or "[]")
                except json.JSONDecodeError:
                    existing = []
                for c in ev:
                    if c not in existing:
                        existing.append(c)
                row.evidence_json = json.dumps(existing)
            else:
                db.add(
                    GraphEdgeModel(
                        id=pk,
                        document_id=document_id,
                        src=src,
                        rel=rel,
                        dst=dst,
                        confidence=float(confidence),
                        evidence_json=json.dumps(ev),
                    )
                )
            db.commit()
        except Exception as e:
            db.rollback()
            log.error(f"GraphStore upsert_edge failed: {e}")
            raise
        finally:
            db.close()

    def get_graph(self, document_id: str) -> DocumentGraph:
        with _graph_cache_lock:
            hit = _graph_cache.get(document_id)
            if hit is not None:
                return hit

        db = self._session()
        try:
            nodes_rows = (
                db.query(GraphNodeModel)
                .filter(GraphNodeModel.document_id == document_id)
                .all()
            )
            edges_rows = (
                db.query(GraphEdgeModel)
                .filter(GraphEdgeModel.document_id == document_id)
                .all()
            )
            nodes = []
            for r in nodes_rows:
                try:
                    aliases = json.loads(r.aliases_json or "[]")
                except json.JSONDecodeError:
                    aliases = []
                try:
                    ev = json.loads(r.evidence_json or "[]")
                except json.JSONDecodeError:
                    ev = []
                nodes.append(
                    GraphNode(
                        id=r.node_id,
                        type=r.node_type or "Entity",
                        name=r.name or r.node_id,
                        aliases=aliases,
                        evidence_chunk_ids=ev,
                    )
                )
            edges = []
            for r in edges_rows:
                try:
                    ev = json.loads(r.evidence_json or "[]")
                except json.JSONDecodeError:
                    ev = []
                edges.append(
                    GraphEdge(
                        src=r.src,
                        rel=r.rel,
                        dst=r.dst,
                        confidence=float(r.confidence or 0.5),
                        evidence_chunk_ids=ev,
                    )
                )
            graph = DocumentGraph(document_id=document_id, nodes=nodes, edges=edges)
            with _graph_cache_lock:
                _graph_cache[document_id] = graph
            return graph
        finally:
            db.close()

    def delete_graph(self, document_id: str) -> None:
        db = self._session()
        try:
            db.query(GraphNodeModel).filter(GraphNodeModel.document_id == document_id).delete()
            db.query(GraphEdgeModel).filter(GraphEdgeModel.document_id == document_id).delete()
            db.commit()
            invalidate_graph_cache(document_id)
        except Exception as e:
            db.rollback()
            log.warning(f"GraphStore delete failed: {e}")
        finally:
            db.close()

    def match_entity_ids(
        self,
        document_id: str,
        query: str,
        *,
        graph: Optional[DocumentGraph] = None,
    ) -> List[str]:
        """Match query text against node names/aliases (case-insensitive substring)."""
        q = (query or "").lower()
        if not q:
            return []
        g = graph if graph is not None else self.get_graph(document_id)
        matched: List[str] = []
        for n in g.nodes:
            names = [n.name] + list(n.aliases)
            for name in names:
                token = (name or "").strip()
                if len(token) < 3:
                    continue
                if token.lower() in q:
                    matched.append(n.id)
                    break
        return matched

    def neighbor_chunk_ids(
        self,
        document_id: str,
        query: str,
        *,
        max_chunks: Optional[int] = None,
        min_confidence: Optional[float] = None,
    ) -> List[str]:
        """
        Chunk ids from matched entities + 1-hop neighbors (edge evidence + node evidence).
        """
        max_n = max_chunks if max_chunks is not None else settings.GRAPH_SEED_MAX_CHUNKS
        min_conf = (
            min_confidence
            if min_confidence is not None
            else float(settings.GRAPH_SEED_MIN_CONFIDENCE)
        )
        graph = self.get_graph(document_id)
        matched = self.match_entity_ids(document_id, query, graph=graph)
        if not matched:
            return []

        node_by_id = {n.id: n for n in graph.nodes}
        seed_nodes: Set[str] = set(matched)

        for e in graph.edges:
            if e.confidence < min_conf:
                continue
            if e.src in matched:
                seed_nodes.add(e.dst)
            if e.dst in matched:
                seed_nodes.add(e.src)

        chunk_ids: List[str] = []
        seen: Set[str] = set()

        def _add_chunks(ids: Sequence[str]) -> None:
            for cid in ids:
                if cid and cid not in seen:
                    seen.add(cid)
                    chunk_ids.append(cid)

        for nid in seed_nodes:
            node = node_by_id.get(nid)
            if node:
                _add_chunks(node.evidence_chunk_ids)

        for e in graph.edges:
            if e.confidence < min_conf:
                continue
            if e.src in seed_nodes or e.dst in seed_nodes:
                _add_chunks(e.evidence_chunk_ids)

        return chunk_ids[:max_n]


def sync_graph_from_knowledge(document_id: str, knowledge: Any = None) -> Optional[DocumentGraph]:
    """
    Convenience: load knowledge (or use provided) and replace graph.
    Called from Understanding write path.
    """
    try:
        if knowledge is None:
            try:
                from src.memory import storage

                raw = storage.get_knowledge(document_id)
            except Exception as e:
                log.warning(f"Could not load knowledge for graph sync: {e}")
                return None
            if not raw:
                return None
            doc = KnowledgeDocument.from_dict(raw)
        elif isinstance(knowledge, KnowledgeDocument):
            doc = knowledge
        elif isinstance(knowledge, dict):
            doc = KnowledgeDocument.from_dict(knowledge)
        else:
            return None
        if not doc.document_id:
            doc.document_id = document_id
        if doc.status in ("failed", "skipped"):
            return None
        return GraphStore().replace_from_knowledge(doc)
    except Exception as e:
        log.warning(f"sync_graph_from_knowledge failed for {document_id}: {e}")
        return None
