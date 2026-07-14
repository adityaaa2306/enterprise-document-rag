import os
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

from src.core.config import settings
from src.agents import models
from src.memory.document_ids import align_chunks_to_document_id
from src.memory.chroma import get_chroma_client, init_chroma
from src.db.session import get_engine, get_session, get_session_factory, init_engine
from src.db.models import ChunkModel, DocumentModel, UserModel

# -----------------------------------------------------------
# Logging Setup
# -----------------------------------------------------------
log = logging.getLogger("storage")
log.setLevel(logging.INFO)

# Backward-compatible aliases (tests / older imports)
engine = None
DBSessionLocal = None

# Re-export models for callers that imported them from storage
__all__ = [
    "ChunkModel",
    "DocumentModel",
    "UserModel",
    "init_database",
    "engine",
    "DBSessionLocal",
]


def _sync_session_aliases() -> None:
    """Keep module-level engine/DBSessionLocal in sync with shared db.session."""
    global engine, DBSessionLocal
    engine = get_engine()
    DBSessionLocal = get_session_factory()


# -----------------------------------------------------------
# ChromaDB — vectors only (see src.memory.chroma). Not Postgres/pgvector.
# Embedded PersistentClient under CHROMA_PERSIST_DIRECTORY.
# -----------------------------------------------------------


def _get_documents_collection():
    """Chroma collection for embeddings (settings.chroma_collection())."""
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=settings.chroma_collection(),
        metadata={"hnsw:space": "cosine"},
    )


# Backward-compatible module attribute (lazy via property-like helper)
def __getattr__(name: str):
    if name == "chroma_client":
        return get_chroma_client()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _session():
    """Open a DB session from the shared factory."""
    return get_session()


# Lazy-init engine on import so callers using DBSessionLocal() keep working
# before main lifespan runs (tests, scripts). Schema still comes from Alembic.
try:
    init_engine()
    _sync_session_aliases()
except Exception as _e:
    log.warning(f"Deferred DB engine init failed (will retry in init_database): {_e}")


# -----------------------------------------------------------
# Chunk Storage Functions
# -----------------------------------------------------------

# -----------------------------------------------------------
# Document ID convention (Phase 2.0)
# -----------------------------------------------------------
# Public RAG / storage key: document_id == job_id (UUID from POST /summarize).
# Triage may stamp a different Chunk.document_id from the filename; that value
# is NOT used for Chroma/SQLite indexing. store_document_data always indexes
# under job_id and realigns chunk.document_id at store time.
# See: src.memory.document_ids.align_chunks_to_document_id


def store_chunks(
    document_id: str,
    chunks: List[Any],
    *,
    prefetched_embeddings: Optional[List[Optional[List[float]]]] = None,
):
    """
    Stores text chunks in SQLite + embeddings in ChromaDB.
    Handles both dicts and Pydantic 'Chunk' objects.
    Generates embeddings via NVIDIA NIM if missing.

    ``document_id`` must be the canonical job_id from /summarize.
    ``prefetched_embeddings`` (optional) skips a second embed pass when
    embeddings were computed in parallel with map/compile.
    """
    try:
        collection = _get_documents_collection()
        db = _session()

        chunks = align_chunks_to_document_id(document_id, chunks)

        nim_ready = models.get_embedding_model()
        if not nim_ready:
            log.warning("NIM embedding client not loaded. RAG search will not work for this doc.")

        # Normalize texts first so we can batch-embed
        # tuple: chunk_id, idx, text, precomputed, parent_id, section_path, chunk_kind, token_estimate
        normalized: List[tuple] = []
        for idx, c in enumerate(chunks):
            chunk_id = f"{document_id}_{idx}"
            text_content = ""
            precomputed = None
            parent_id = None
            section_path = None
            chunk_kind = None
            token_estimate = None
            if isinstance(c, dict):
                text_content = c.get("text") or c.get("content") or ""
                precomputed = c.get("embedding")
                parent_id = c.get("parent_id")
                section_path = c.get("section_path")
                chunk_kind = c.get("chunk_kind")
                token_estimate = c.get("token_estimate")
            else:
                text_content = getattr(c, "content", "")
                parent_id = getattr(c, "parent_id", None)
                section_path = getattr(c, "section_path", None)
                chunk_kind = getattr(c, "chunk_kind", None)
                token_estimate = getattr(c, "token_estimate", None)

            if not text_content:
                continue
            # Prefer explicit chunk embedding, else prefetch by original index
            if precomputed is None and prefetched_embeddings is not None and idx < len(
                prefetched_embeddings
            ):
                precomputed = prefetched_embeddings[idx]
            normalized.append(
                (
                    chunk_id,
                    idx,
                    text_content,
                    precomputed,
                    parent_id,
                    section_path,
                    chunk_kind,
                    token_estimate,
                )
            )

        # Batch embed texts that lack a precomputed vector
        to_embed_indices = [i for i, t in enumerate(normalized) if t[3] is None]
        embeddings_by_pos: Dict[int, List[float]] = {}
        if nim_ready and to_embed_indices:
            texts_to_embed = [normalized[i][2] for i in to_embed_indices]
            try:
                vectors = models.embed_texts(texts_to_embed)
                for pos, vec in zip(to_embed_indices, vectors):
                    embeddings_by_pos[pos] = vec
            except Exception as e:
                log.error(f"NIM embedding failed during store: {e}")

        # Batch SQL merges + single (or few) Chroma upserts
        chroma_ids: List[str] = []
        chroma_embeddings: List[List[float]] = []
        chroma_metas: List[dict] = []
        chroma_docs: List[str] = []

        for pos, row in enumerate(normalized):
            (
                chunk_id,
                idx,
                text_content,
                precomputed,
                parent_id,
                section_path,
                chunk_kind,
                token_estimate,
            ) = row
            db_chunk = ChunkModel(
                id=chunk_id,
                document_id=document_id,
                chunk_index=str(idx),
                text=text_content,
                parent_id=parent_id,
                section_path=section_path,
                chunk_kind=chunk_kind,
                token_estimate=token_estimate,
            )
            db.merge(db_chunk)

            embedding = precomputed if precomputed is not None else embeddings_by_pos.get(pos)
            if embedding is not None:
                meta = {
                    "document_id": document_id,
                    "chunk_index": idx,
                }
                if parent_id:
                    meta["parent_id"] = str(parent_id)
                if section_path:
                    meta["section_path"] = str(section_path)[:500]
                if chunk_kind:
                    meta["chunk_kind"] = str(chunk_kind)
                if token_estimate is not None:
                    meta["token_estimate"] = int(token_estimate)
                chroma_ids.append(chunk_id)
                chroma_embeddings.append(embedding)
                chroma_metas.append(meta)
                chroma_docs.append(text_content)

        # Bulk Chroma upsert in batches of 64 (same vectors, far fewer RPC round-trips)
        BATCH = 64
        for i in range(0, len(chroma_ids), BATCH):
            collection.upsert(
                ids=chroma_ids[i : i + BATCH],
                embeddings=chroma_embeddings[i : i + BATCH],
                metadatas=chroma_metas[i : i + BATCH],
                documents=chroma_docs[i : i + BATCH],
            )

        db.commit()
        db.close()

        # Rebuild BM25 sparse index for hybrid retrieval (Phase 2.B)
        try:
            from src.retrieval.bm25 import build_and_save

            bm25_docs = [(row[0], row[2]) for row in normalized]  # chunk_id, text
            build_and_save(document_id, bm25_docs)
        except Exception as e:
            log.warning(f"BM25 index rebuild failed for {document_id}: {e}")

        log.info(f"Stored {len(normalized)} chunks for document {document_id}")
        return True

    except Exception as e:
        log.error(f"Failed to store chunks: {e}")
        return False


def search_similar_chunks(query: str, document_id: str, k: int = None) -> List[Any]:
    """
    Hybrid (or dense-only) retrieve via RetrievalService, then return
    objects with a `.content` attribute for the RAG runner.
    """
    try:
        from src.retrieval.service import search_as_content_chunks

        return search_as_content_chunks(query, document_id, k=k)
    except Exception as e:
        log.error(f"Failed to search similar chunks: {e}")
        raise e


def retrieve_chunks(document_id: str):
    db = _session()
    try:
        rows = db.query(ChunkModel).filter(ChunkModel.document_id == document_id).all()
        return [{"text": r.text, "index": r.chunk_index} for r in rows]
    finally:
        db.close()


def delete_chunks(document_id: str):
    try:
        db = _session()
        db.query(ChunkModel).filter(ChunkModel.document_id == document_id).delete()
        db.commit()
        db.close()

        collection = _get_documents_collection()
        all_ids = [f"{document_id}_{i}" for i in range(5000)]
        collection.delete(ids=all_ids)

        try:
            from src.retrieval.bm25 import delete_index

            delete_index(document_id)
        except Exception as e:
            log.warning(f"BM25 index delete failed for {document_id}: {e}")

        try:
            from src.memory.service import MemoryService

            MemoryService().invalidate_document(document_id)
        except Exception as e:
            log.warning(f"Memory invalidate on delete failed for {document_id}: {e}")

        log.info(f"Deleted chunks for document {document_id}")

    except Exception as e:
        log.error(f"Failed to delete chunks: {e}")

# -----------------------------------------------------------
# Initialization (Called by Main.py)
# -----------------------------------------------------------
def init_database(*, block_on_chroma: bool = True):
    """
    Called by API lifespan / worker startup.

    Schema migrations are owned by the Docker entrypoint
    (`alembic upgrade head` when RUN_MIGRATIONS_ON_STARTUP=true).

    Chroma is embedded (PersistentClient): init is local disk I/O only and
    must not block PORT bind with network retries. ``block_on_chroma`` is
    retained for call-site compatibility but both paths init immediately.
    """
    try:
        init_engine()
        _sync_session_aliases()
        if getattr(settings, "AUTO_CREATE_SCHEMA", False):
            if settings.is_production:
                log.error("Refusing AUTO_CREATE_SCHEMA in production — use Alembic.")
            else:
                from src.db.base import Base
                import src.db.models  # noqa: F401 — register models

                Base.metadata.create_all(bind=get_engine())
                log.warning(
                    "AUTO_CREATE_SCHEMA=true: created tables via metadata.create_all (prefer Alembic)."
                )
        log.info(f"Relational DB ready ({settings.DATABASE_URL.split(':', 1)[0]})")
    except Exception as e:
        log.error(f"Failed to initialize relational DB: {e}")
        raise

    info = init_chroma()
    if info.get("ok"):
        log.info(
            "Chroma PersistentClient ready path=%s collection=%s",
            info.get("path"),
            info.get("collection"),
        )
    else:
        # Do not raise — /api/ready reports failure; lifespan must still yield.
        log.error("Chroma init failed at startup: %s", info.get("error") or info)

# -----------------------------------------------------------
# FINAL SUMMARY STORAGE
# -----------------------------------------------------------

def store_document_data(
    job_id: str,
    summary: str,
    chunks: List[Any],
    carbon_meta: Dict[str, Any] = None,
    routing_decision: Dict[str, Any] = None,
    user_id: Optional[int] = None,
    prefetched_embeddings: Optional[List[Optional[List[float]]]] = None,
):
    """
    Stores the final summary generated by the reduce agent.
    Updated to match Orchestrator signature.
    ADDED: carbon_meta for dashboard analytics.
    Phase 2.D: optional routing_decision persisted for query-time model chains.
    Phase 1: optional user_id ownership stamp.

    Canonical document_id for RAG is ``job_id`` (same UUID returned by POST /summarize
    as both job_id and document_id).
    """
    document_id = job_id

    if carbon_meta is None:
        carbon_meta = {}

    # Prefer explicit user_id; else inherit from job row if present
    if user_id is None:
        try:
            from src.db import jobs as job_store

            job = job_store.get_job(document_id) or {}
            if job.get("user_id") is not None:
                user_id = int(job["user_id"])
        except Exception:
            pass

    routing_payload = routing_decision if isinstance(routing_decision, dict) else None
    selected_model = routing_payload.get("selected_model") if routing_payload else None
    crs = routing_payload.get("crs") if routing_payload else None

    has_carbon = bool(carbon_meta)

    # 1. Store the summary and carbon stats
    try:
        db = _session()
        doc = db.get(DocumentModel, document_id)

        if doc:
            doc.summary = summary
            if has_carbon:
                doc.carbon_saved_grams = float(carbon_meta.get("carbon_saved_grams") or 0.0)
                doc.processing_time_seconds = float(
                    carbon_meta.get("processing_time_seconds") or 0.0
                )
                doc.total_chunks = int(carbon_meta.get("total_chunks") or 0)
                doc.efficiency_percent = float(carbon_meta.get("efficiency_percent") or 0.0)
                doc.actual_cost_gco2e = float(carbon_meta.get("actual_cost_gco2e") or 0.0)
                doc.baseline_cost_gco2e = float(carbon_meta.get("baseline_cost_gco2e") or 0.0)
            if user_id is not None and doc.user_id is None:
                doc.user_id = int(user_id)
            if routing_payload is not None:
                doc.routing_json = routing_payload
                if selected_model is not None:
                    doc.selected_model = selected_model
                if crs is not None:
                    doc.crs = float(crs)
        else:
            doc = DocumentModel(
                id=document_id,
                summary=summary,
                user_id=int(user_id) if user_id is not None else None,
                carbon_saved_grams=float(carbon_meta.get("carbon_saved_grams") or 0.0),
                processing_time_seconds=float(
                    carbon_meta.get("processing_time_seconds") or 0.0
                ),
                total_chunks=int(carbon_meta.get("total_chunks") or 0),
                efficiency_percent=float(carbon_meta.get("efficiency_percent") or 0.0),
                actual_cost_gco2e=float(carbon_meta.get("actual_cost_gco2e") or 0.0),
                baseline_cost_gco2e=float(carbon_meta.get("baseline_cost_gco2e") or 0.0),
                routing_json=routing_payload,
                selected_model=selected_model,
                crs=float(crs) if crs is not None else None,
            )
            db.add(doc)

        db.commit()
        db.close()
        log.info(f"Final summary and stats stored for document {document_id}")
    except Exception as e:
        log.error(f"Failed to store final summary: {e}")

    # 2. Store the chunks (aligned to canonical document_id / job_id)
    if chunks:
        aligned = align_chunks_to_document_id(document_id, chunks)
        success = store_chunks(
            document_id,
            aligned,
            prefetched_embeddings=prefetched_embeddings,
        )
        if success:
            log.info(f"RAG: Stored {len(aligned)} chunks for {document_id}")
        else:
            log.error(f"RAG: Failed to store chunks for {document_id}")

    return {"status": "ok", "document_id": document_id}


def get_document_user_id(document_id: str) -> Optional[int]:
    """Return owning user_id for a document, or None."""
    try:
        db = _session()
        doc = db.get(DocumentModel, document_id)
        uid = doc.user_id if doc else None
        db.close()
        return int(uid) if uid is not None else None
    except Exception as e:
        log.warning(f"get_document_user_id failed: {e}")
        return None


def ensure_document_owner(document_id: str, user_id: int) -> None:
    """Create a stub document row with ownership if missing (pre-job indexing)."""
    try:
        db = _session()
        doc = db.get(DocumentModel, document_id)
        if doc is None:
            doc = DocumentModel(id=document_id, summary="", user_id=int(user_id))
            db.add(doc)
        elif doc.user_id is None:
            doc.user_id = int(user_id)
        db.commit()
        db.close()
    except Exception as e:
        log.warning(f"ensure_document_owner failed: {e}")


def save_document_file_metadata(
    document_id: str,
    *,
    user_id: Optional[int] = None,
    storage_key: Optional[str] = None,
    file_url: Optional[str] = None,
    original_filename: Optional[str] = None,
    content_type: Optional[str] = None,
    byte_size: Optional[int] = None,
) -> None:
    """Persist object-storage pointers on the documents row (Phase 2)."""
    try:
        db = _session()
        doc = db.get(DocumentModel, document_id)
        if doc is None:
            doc = DocumentModel(id=document_id, summary="", user_id=user_id)
            db.add(doc)
        if user_id is not None and doc.user_id is None:
            doc.user_id = int(user_id)
        if storage_key is not None:
            doc.storage_key = storage_key
        if file_url is not None:
            doc.file_url = file_url
        if original_filename is not None:
            doc.original_filename = original_filename
        if content_type is not None:
            doc.content_type = content_type
        if byte_size is not None:
            doc.byte_size = int(byte_size)
        db.commit()
        db.close()
    except Exception as e:
        log.warning(f"save_document_file_metadata failed: {e}")


def get_document_storage_key(document_id: str) -> Optional[str]:
    """Return object-storage key for a document, if any."""
    try:
        db = _session()
        doc = db.get(DocumentModel, document_id)
        key = doc.storage_key if doc else None
        db.close()
        return key
    except Exception as e:
        log.warning(f"get_document_storage_key failed: {e}")
        return None


def get_routing_decision(document_id: str) -> Optional[Dict[str, Any]]:
    """Load persisted RoutingDecision dict for a document (Phase 2.D)."""
    import json

    try:
        db = _session()
        doc = db.get(DocumentModel, document_id)
        raw = doc.routing_json if doc else None
        db.close()
        if not raw:
            return None
        if isinstance(raw, dict):
            return raw
        data = json.loads(raw) if isinstance(raw, str) else raw
        return data if isinstance(data, dict) else None
    except Exception as e:
        log.warning(f"Failed to load routing_decision for {document_id}: {e}")
        return None


def save_knowledge(document_id: str, knowledge: Any) -> bool:
    """Persist KnowledgeDocument (or dict) as knowledge_json (Phase 2.F)."""
    try:
        if hasattr(knowledge, "to_dict"):
            payload = knowledge.to_dict()
        elif isinstance(knowledge, dict):
            payload = knowledge
        else:
            raise TypeError("knowledge must be KnowledgeDocument or dict")
        db = _session()
        doc = db.get(DocumentModel, document_id)
        if not doc:
            doc = DocumentModel(id=document_id, summary="")
            db.add(doc)
        doc.knowledge_json = payload
        db.commit()
        db.close()
        log.info(f"Knowledge saved for document {document_id}")
        return True
    except Exception as e:
        log.error(f"Failed to save knowledge for {document_id}: {e}")
        return False


def get_knowledge(document_id: str) -> Optional[Dict[str, Any]]:
    """Load KnowledgeDocument dict for a document (Phase 2.F)."""
    import json

    try:
        db = _session()
        doc = db.get(DocumentModel, document_id)
        raw = doc.knowledge_json if doc else None
        db.close()
        if not raw:
            return None
        if isinstance(raw, dict):
            return raw
        data = json.loads(raw) if isinstance(raw, str) else raw
        return data if isinstance(data, dict) else None
    except Exception as e:
        log.warning(f"Failed to load knowledge for {document_id}: {e}")
        return None


def get_document_data(document_id: str) -> Optional[str]:
    """
    Retrieve the final summary (used by UI).
    """
    try:
        db = _session()
        doc = db.get(DocumentModel, document_id)
        db.close()
        return doc.summary if doc else None

    except Exception as e:
        log.error(f"Failed to fetch document summary: {e}")
        return None


def delete_document_data(document_id: str):
    try:
        db = _session()
        doc = db.get(DocumentModel, document_id)
        if doc:
            db.delete(doc)
            db.commit()
        db.close()
        log.info(f"Deleted document-level data for {document_id}")
    except Exception as e:
        log.error(f"Failed to delete document summary: {e}")


def list_documents(user_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    List stored documents. When user_id is set, only that user's documents.
    """
    try:
        db = _session()
        q = db.query(DocumentModel)
        if user_id is not None:
            q = q.filter(DocumentModel.user_id == int(user_id))
        docs = q.order_by(DocumentModel.saved_at.desc()).all()
        result = []
        for doc in docs:
            result.append({
                "document_id": doc.id,
                "summary": doc.summary,
                "saved_at": doc.saved_at.isoformat() if doc.saved_at else None,
                "carbon_saved": doc.carbon_saved_grams,
                "efficiency": doc.efficiency_percent
            })
        db.close()
        return result
    except Exception as e:
        log.error(f"Failed to list documents: {e}")
        return []

def get_dashboard_stats(
    user_id: Optional[int] = None,
    *,
    range_key: str = "30d",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Aggregates dashboard analytics (scoped to user_id when provided).

    Date labels are unique calendar days (YYYY-MM-DD → "Jul 13"), not one row
    per document — which previously caused repeated "Jul 13" tick labels.

    Actual emissions come from completed jobs (actual_cost_gco2e).
    Baseline emissions use the ChatGPT/frontier published estimate
    (baseline_cost_gco2e), backfilled from job results or chunk counts when
    older rows lack explicit fields.
    """
    from datetime import timedelta, timezone
    from collections import defaultdict

    empty = {
        "total_carbon_saved": 0.0,
        "total_carbon_consumed": 0.0,
        "total_baseline_carbon": 0.0,
        "total_docs": 0,
        "avg_efficiency": 0.0,
        "carbon_trend": [],
        "energy_trend": [],
        "range": range_key or "30d",
        "start_date": None,
        "end_date": None,
        "point_count": 0,
        "empty_state_message": None,
    }

    def _resolve_doc_carbon(d: DocumentModel) -> Optional[Dict[str, float]]:
        """Return actual/baseline/saved/eff for a completed document, or None.

        Uses stored workflow accounting (energy × Electricity Maps). Does not
        invent grams from chunk counts.
        """
        chunks = int(getattr(d, "total_chunks", 0) or 0)
        actual = float(getattr(d, "actual_cost_gco2e", 0.0) or 0.0)
        baseline = float(getattr(d, "baseline_cost_gco2e", 0.0) or 0.0)
        saved = float(d.carbon_saved_grams or 0.0)
        eff = float(d.efficiency_percent or 0.0)

        if (chunks <= 0 or actual <= 0 or baseline <= 0) and d.id:
            try:
                from src.db import jobs as job_store

                job = job_store.get_job(d.id) or {}
                status = str(job.get("status") or "").lower()
                if status in ("error", "failed", "cancelled", "canceled"):
                    return None
                result = job.get("result") if isinstance(job.get("result"), dict) else {}
                carbon = (
                    result.get("carbon_data")
                    if isinstance(result.get("carbon_data"), dict)
                    else {}
                )
                if carbon:
                    chunks = int(carbon.get("total_chunks") or chunks or 0)
                    if actual <= 0:
                        actual = float(carbon.get("actual_cost_gco2e") or 0.0)
                    if baseline <= 0:
                        baseline = float(carbon.get("baseline_cost_gco2e") or 0.0)
                    if saved == 0:
                        saved = float(carbon.get("carbon_saved_grams") or 0.0)
                    if eff == 0:
                        eff = float(carbon.get("efficiency_percent") or 0.0)
            except Exception:
                pass

        if chunks <= 0:
            return None
        if actual <= 0 and baseline <= 0 and saved == 0:
            return None

        if baseline <= 0 and saved > 0 and eff > 0:
            baseline = saved / (eff / 100.0)
        if actual <= 0 and baseline > 0:
            actual = max(0.0, baseline - max(0.0, saved))
        if baseline > 0:
            saved = max(0.0, baseline - actual)
            eff = min(100.0, (saved / baseline) * 100.0)
        else:
            return None

        return {
            "chunks": float(chunks),
            "actual": float(actual),
            "baseline": float(baseline),
            "saved": float(saved),
            "efficiency": float(eff),
        }

    try:
        db = _session()
        q = db.query(DocumentModel)
        if user_id is not None:
            q = q.filter(DocumentModel.user_id == int(user_id))
        docs = q.all()

        now = datetime.now(timezone.utc)
        key = (range_key or "30d").strip().lower()

        def _parse_day(value: Optional[str]) -> Optional[datetime]:
            if not value:
                return None
            try:
                return datetime.strptime(value[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except Exception:
                return None

        start_dt: Optional[datetime] = None
        end_dt: Optional[datetime] = now

        if key == "today":
            start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif key == "7d":
            start_dt = now - timedelta(days=7)
        elif key == "90d":
            start_dt = now - timedelta(days=90)
        elif key == "custom":
            start_dt = _parse_day(start_date)
            parsed_end = _parse_day(end_date)
            if parsed_end is not None:
                end_dt = parsed_end.replace(hour=23, minute=59, second=59, microsecond=999999)
            if start_dt is None and parsed_end is None:
                start_dt = now - timedelta(days=30)
        else:
            key = "30d"
            start_dt = now - timedelta(days=30)

        def _aware(dt: Optional[datetime]) -> Optional[datetime]:
            if dt is None:
                return None
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt

        filtered = []
        for d in docs:
            saved_at = _aware(d.saved_at)
            if saved_at is None:
                continue
            if start_dt is not None and saved_at < _aware(start_dt):
                continue
            if end_dt is not None and saved_at > _aware(end_dt):
                continue
            filtered.append(d)

        grid = float(getattr(settings, "LOCAL_GRID_INTENSITY", 700.0) or 700.0)

        daily: Dict[str, Dict[str, float]] = defaultdict(
            lambda: {
                "saved": 0.0,
                "baseline": 0.0,
                "actual": 0.0,
                "efficiency_sum": 0.0,
                "docs": 0.0,
                "processing_seconds": 0.0,
            }
        )

        resolved_rows: List[Dict[str, float]] = []
        for d in filtered:
            carbon = _resolve_doc_carbon(d)
            if carbon is None:
                continue
            saved_at = _aware(d.saved_at)
            assert saved_at is not None
            day_key = saved_at.strftime("%Y-%m-%d")
            bucket = daily[day_key]
            bucket["saved"] += carbon["saved"]
            bucket["baseline"] += carbon["baseline"]
            bucket["actual"] += carbon["actual"]
            bucket["efficiency_sum"] += carbon["efficiency"]
            bucket["docs"] += 1.0
            bucket["processing_seconds"] += float(d.processing_time_seconds or 0.0)
            resolved_rows.append(carbon)

        carbon_trend = []
        energy_trend = []
        for day_key in sorted(daily.keys()):
            bucket = daily[day_key]
            docs_n = int(bucket["docs"])
            avg_eff = (bucket["efficiency_sum"] / docs_n) if docs_n else 0.0
            day_dt = datetime.strptime(day_key, "%Y-%m-%d")
            label = day_dt.strftime("%b %d")
            actual = bucket["actual"]
            baseline = bucket["baseline"]
            saved = bucket["saved"]
            energy_kwh = (actual / grid) if grid > 0 else 0.0

            carbon_trend.append(
                {
                    "date": label,
                    "date_iso": day_key,
                    "savings": round(saved, 4),
                    "carbon_saved": round(saved, 4),
                    "baseline": round(baseline, 4),
                    "actual": round(actual, 4),
                    "efficiency": round(avg_eff, 2),
                    "docs_processed": docs_n,
                }
            )
            energy_trend.append(
                {
                    "date": label,
                    "date_iso": day_key,
                    "energy_consumed_kwh": round(energy_kwh, 6),
                    "estimated_co2e": round(actual, 4),
                    "docs_processed": docs_n,
                    "processing_seconds": round(bucket["processing_seconds"], 2),
                }
            )

        total_docs = len(resolved_rows)
        total_carbon_saved = sum(row["saved"] for row in resolved_rows)
        total_baseline = sum(row["baseline"] for row in resolved_rows)
        total_actual = sum(row["actual"] for row in resolved_rows)
        avg_efficiency = (
            sum(row["efficiency"] for row in resolved_rows) / total_docs if total_docs else 0.0
        )

        point_count = len(carbon_trend)
        empty_msg = None
        if total_docs <= 1 or point_count < 2:
            empty_msg = "More analytics will appear as additional documents are processed."

        db.close()

        return {
            "total_carbon_saved": round(total_carbon_saved, 4),
            "total_carbon_consumed": round(total_actual, 4),
            "total_baseline_carbon": round(total_baseline, 4),
            "total_docs": total_docs,
            "avg_efficiency": round(avg_efficiency, 2),
            "carbon_trend": carbon_trend,
            "energy_trend": energy_trend,
            "range": key,
            "start_date": start_dt.date().isoformat() if start_dt else None,
            "end_date": end_dt.date().isoformat() if end_dt else None,
            "point_count": point_count,
            "empty_state_message": empty_msg,
        }
    except Exception as e:
        log.error(f"Failed to get dashboard stats: {e}")
        return empty


# -----------------------------------------------------------
# USER MANAGEMENT FUNCTIONS
# -----------------------------------------------------------

def create_user(email: str, hashed_password: str, full_name: str) -> Optional[Dict[str, Any]]:
    """
    Create a new user account.
    Returns user info if successful, None if email already exists.
    """
    try:
        db = _session()
        
        # Check if user already exists
        existing_user = db.query(UserModel).filter(UserModel.email == email).first()
        if existing_user:
            db.close()
            return None
        
        # Create new user
        new_user = UserModel(
            email=email,
            hashed_password=hashed_password,
            full_name=full_name
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        user_data = {
            "id": new_user.id,
            "email": new_user.email,
            "full_name": new_user.full_name,
            "is_active": new_user.is_active,
            "created_at": new_user.created_at.isoformat() if new_user.created_at else None
        }
        
        db.close()
        log.info(f"Created new user: {email}")
        return user_data
        
    except Exception as e:
        log.error(f"Failed to create user: {e}")
        return None


def get_user_by_email(email: str):
    """
    Retrieve a user by email address.
    Returns the full UserModel (including hashed_password) for authentication.
    """
    try:
        db = _session()
        user = db.query(UserModel).filter(UserModel.email == email).first()
        db.close()
        return user
    except Exception as e:
        log.error(f"Failed to get user by email: {e}")
        return None


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    """
    Retrieve a user by ID.
    Returns user info (without password) for display purposes.
    """
    try:
        db = _session()
        user = db.get(UserModel, user_id)
        
        if not user:
            db.close()
            return None
        
        user_data = {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat() if user.created_at else None
        }
        
        db.close()
        return user_data
        
    except Exception as e:
        log.error(f"Failed to get user by ID: {e}")
        return None

