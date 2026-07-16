"""
MemoryService — unified document / conversation / cache facade (Phase 2.H).

Not an agent. Wraps embedding cache, document metadata, and TTL conversation memory.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from src.core.config import settings

log = logging.getLogger(__name__)
_lock = threading.Lock()


@dataclass
class ConversationTurn:
    role: str  # user|assistant
    content: str
    entities: List[str] = field(default_factory=list)
    ts: float = field(default_factory=lambda: time.time())
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ConversationTurn":
        return cls(
            role=str(d.get("role") or "user"),
            content=str(d.get("content") or ""),
            entities=[str(e) for e in (d.get("entities") or [])],
            ts=float(d.get("ts") or time.time()),
            meta=dict(d.get("meta") or {}),
        )


@dataclass
class ConversationState:
    conversation_id: str
    document_id: str
    turns: List[ConversationTurn] = field(default_factory=list)
    created_at: float = field(default_factory=lambda: time.time())
    updated_at: float = field(default_factory=lambda: time.time())
    owner_type: Optional[str] = None
    owner_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "conversation_id": self.conversation_id,
            "document_id": self.document_id,
            "turns": [t.to_dict() for t in self.turns],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.owner_type:
            d["owner_type"] = self.owner_type
        if self.owner_id:
            d["owner_id"] = self.owner_id
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ConversationState":
        return cls(
            conversation_id=str(d.get("conversation_id") or ""),
            document_id=str(d.get("document_id") or ""),
            turns=[ConversationTurn.from_dict(t) for t in (d.get("turns") or []) if isinstance(t, dict)],
            created_at=float(d.get("created_at") or time.time()),
            updated_at=float(d.get("updated_at") or time.time()),
            owner_type=str(d["owner_type"]) if d.get("owner_type") else None,
            owner_id=str(d["owner_id"]) if d.get("owner_id") else None,
        )


def _conv_dir() -> str:
    path = os.path.join(settings.VECTOR_DB_PATH, "conversations")
    os.makedirs(path, exist_ok=True)
    return path


def _conv_path(conversation_id: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in conversation_id)
    return os.path.join(_conv_dir(), f"{safe}.json")


class MemoryService:
    """Facade over embedding cache, document store helpers, and conversation TTL memory."""

    # --- Embedding cache ---

    def embed_cache_stats(self) -> Dict[str, int]:
        from src.memory import embedding_cache

        return embedding_cache.stats()

    def embed_cache_get_many(self, model_id: str, texts: List[str]):
        from src.memory import embedding_cache

        return embedding_cache.get_many(model_id, texts)

    def embed_cache_put_many(self, model_id: str, texts: List[str], embeddings: List[List[float]]) -> None:
        from src.memory import embedding_cache

        embedding_cache.put_many(model_id, texts, embeddings)

    # --- Document memory ---

    def get_routing(self, document_id: str) -> Optional[Dict[str, Any]]:
        try:
            from src.memory import storage

            return storage.get_routing_decision(document_id)
        except Exception as e:
            log.warning(f"MemoryService.get_routing failed: {e}")
            return None

    def get_knowledge(self, document_id: str) -> Optional[Dict[str, Any]]:
        try:
            from src.memory import storage

            return storage.get_knowledge(document_id)
        except Exception as e:
            log.warning(f"MemoryService.get_knowledge failed: {e}")
            return None

    def get_summary(self, document_id: str) -> Optional[str]:
        try:
            from src.memory import storage

            return storage.get_document_data(document_id)
        except Exception as e:
            log.warning(f"MemoryService.get_summary failed: {e}")
            return None

    def invalidate_document(self, document_id: str) -> Dict[str, Any]:
        """
        Invalidate document-scoped sidecars after reindex.
        Embedding cache is content-addressed (not cleared wholesale).
        Clears BM25 index + graph + conversations for this document.
        """
        cleared = {"bm25": False, "graph": False, "conversations": 0}
        try:
            from src.retrieval.bm25 import delete_index

            delete_index(document_id)
            cleared["bm25"] = True
        except Exception as e:
            log.warning(f"BM25 invalidate failed: {e}")
        try:
            from src.knowledge.graph_store import GraphStore

            GraphStore().delete_graph(document_id)
            cleared["graph"] = True
        except Exception as e:
            log.warning(f"Graph invalidate failed: {e}")
        cleared["conversations"] = self.clear_conversations_for_document(document_id)
        log.info(f"MemoryService invalidated document {document_id}: {cleared}")
        return cleared

    # --- Conversation memory (TTL) ---

    def ttl_seconds(self) -> float:
        return float(settings.CONVERSATION_TTL_HOURS) * 3600.0

    def _expired(self, state: ConversationState) -> bool:
        return (time.time() - float(state.updated_at)) > self.ttl_seconds()

    def get_conversation(self, conversation_id: str) -> Optional[ConversationState]:
        # Prefer DB when durable conversations are enabled
        if getattr(settings, "PERSIST_CONVERSATIONS_TO_DB", True):
            try:
                from src.db import conversations as conv_db

                data = conv_db.load_conversation(conversation_id)
                if data:
                    return ConversationState.from_dict(data)
                # Expired or missing in DB — also clear legacy file if present
            except Exception as e:
                log.warning(f"DB conversation load failed, trying file: {e}")

        path = _conv_path(conversation_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            state = ConversationState.from_dict(data)
            if self._expired(state):
                self.delete_conversation(conversation_id)
                return None
            return state
        except Exception as e:
            log.warning(f"Load conversation failed: {e}")
            return None

    def save_conversation(
        self,
        state: ConversationState,
        *,
        owner_type: str,
        owner_id: str,
        user_id: Optional[int] = None,
    ) -> None:
        state.updated_at = time.time()
        state.owner_type = str(owner_type)
        state.owner_id = str(owner_id)
        if getattr(settings, "PERSIST_CONVERSATIONS_TO_DB", True):
            try:
                from src.db import conversations as conv_db

                ok = conv_db.save_conversation_state(
                    state.conversation_id,
                    state.document_id,
                    [t.to_dict() for t in state.turns],
                    owner_type=owner_type,
                    owner_id=owner_id,
                    user_id=user_id,
                    created_at=state.created_at,
                )
                if ok:
                    return
            except PermissionError:
                raise
            except Exception as e:
                log.warning(f"DB conversation save failed, falling back to file: {e}")

        path = _conv_path(state.conversation_id)
        tmp = path + ".tmp"
        # Refuse file overwrite when an existing file belongs to someone else.
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    prior = json.load(f)
                pot, poid = prior.get("owner_type"), prior.get("owner_id")
                if pot and poid and (
                    str(pot) != str(owner_type) or str(poid) != str(owner_id)
                ):
                    raise PermissionError("Conversation ownership mismatch")
            except PermissionError:
                raise
            except Exception:
                pass
        payload = state.to_dict()
        payload["owner_type"] = owner_type
        payload["owner_id"] = owner_id
        with _lock:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            os.replace(tmp, path)

    def delete_conversation(self, conversation_id: str) -> None:
        if getattr(settings, "PERSIST_CONVERSATIONS_TO_DB", True):
            try:
                from src.db import conversations as conv_db

                conv_db.delete_conversation(conversation_id)
            except Exception as e:
                log.warning(f"DB conversation delete failed: {e}")
        path = _conv_path(conversation_id)
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError as e:
            log.warning(f"Delete conversation failed: {e}")

    def start_conversation(
        self,
        document_id: str,
        conversation_id: Optional[str] = None,
        *,
        owner_type: str,
        owner_id: str,
        user_id: Optional[int] = None,
    ) -> ConversationState:
        from src.core.owner import owners_match

        cid = conversation_id or str(uuid.uuid4())
        existing = self.get_conversation(cid)
        if existing and existing.document_id == document_id:
            # IDOR guard: never return another owner's conversation.
            if existing.owner_type and existing.owner_id:
                if not owners_match(
                    {"owner_type": owner_type, "owner_id": owner_id},
                    owner_type=str(existing.owner_type),
                    owner_id=str(existing.owner_id),
                ):
                    raise PermissionError("Conversation ownership mismatch")
            elif existing.turns:
                # Legacy conversation without owner stamp — fail closed.
                raise PermissionError("Conversation ownership unknown")
            return existing
        if existing and existing.document_id != document_id:
            raise PermissionError("Conversation/document mismatch")
        state = ConversationState(
            conversation_id=cid,
            document_id=document_id,
            owner_type=str(owner_type),
            owner_id=str(owner_id),
        )
        self.save_conversation(
            state, owner_type=owner_type, owner_id=owner_id, user_id=user_id
        )
        return state

    def append_turn(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        entities: Optional[List[str]] = None,
        meta: Optional[Dict[str, Any]] = None,
        owner_type: str,
        owner_id: str,
        user_id: Optional[int] = None,
    ) -> Optional[ConversationState]:
        from src.core.owner import owners_match

        state = self.get_conversation(conversation_id)
        if not state:
            return None
        if state.owner_type and state.owner_id:
            if not owners_match(
                {"owner_type": owner_type, "owner_id": owner_id},
                owner_type=str(state.owner_type),
                owner_id=str(state.owner_id),
            ):
                raise PermissionError("Conversation ownership mismatch")
        state.turns.append(
            ConversationTurn(
                role=role,
                content=content,
                entities=list(entities or []),
                meta=dict(meta or {}),
            )
        )
        # Cap history
        max_turns = int(getattr(settings, "CONVERSATION_MAX_TURNS", 40) or 40)
        if len(state.turns) > max_turns:
            state.turns = state.turns[-max_turns:]
        self.save_conversation(
            state, owner_type=owner_type, owner_id=owner_id, user_id=user_id
        )
        return state

    def prior_entity_resolutions(self, conversation_id: str) -> List[str]:
        """Entity ids mentioned in prior assistant/user turns within TTL."""
        state = self.get_conversation(conversation_id)
        if not state:
            return []
        seen: List[str] = []
        for turn in state.turns:
            for e in turn.entities:
                if e and e not in seen:
                    seen.append(e)
        return seen

    def clear_conversations_for_document(self, document_id: str) -> int:
        n = 0
        if getattr(settings, "PERSIST_CONVERSATIONS_TO_DB", True):
            try:
                from src.db import conversations as conv_db

                n += conv_db.clear_for_document(document_id)
            except Exception as e:
                log.warning(f"DB clear conversations failed: {e}")
        root = _conv_dir()
        if not os.path.isdir(root):
            return n
        for name in os.listdir(root):
            if not name.endswith(".json"):
                continue
            path = os.path.join(root, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("document_id") == document_id:
                    os.remove(path)
                    n += 1
            except Exception:
                continue
        return n


# Module-level singleton for convenience
memory = MemoryService()
