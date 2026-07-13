"""
All relational ORM models under a single declarative Base.

Embeddings / vectors are NOT stored here — ChromaDB remains the vector store.
"""
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from src.db.base import Base
from src.db.types import FlexibleJSON, JSONType


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class UserModel(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    email = Column(String(320), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class RefreshTokenModel(Base):
    """
    Opaque refresh tokens (stored hashed). Supports rotation + revocation.
    """
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index("ix_refresh_tokens_user_id", "user_id"),
        Index("ix_refresh_tokens_expires", "expires_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # sha256 hex of the raw token
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    replaced_by_hash = Column(String(64), nullable=True)
    user_agent = Column(String(512), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("UserModel", foreign_keys=[user_id])


# ---------------------------------------------------------------------------
# Documents / chunks
# ---------------------------------------------------------------------------


class DocumentModel(Base):
    __tablename__ = "documents"

    id = Column(String(64), primary_key=True, index=True)
    summary = Column(Text)
    saved_at = Column(DateTime(timezone=True), server_default=func.now())

    # Optional ownership (nullable for backward compatibility with anonymous jobs)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    # Analytics
    carbon_saved_grams = Column(Float, default=0.0)
    processing_time_seconds = Column(Float, default=0.0)
    total_chunks = Column(Integer, default=0)
    efficiency_percent = Column(Float, default=0.0)
    # Explicit emissions (preferred over deriving from saved/efficiency alone)
    actual_cost_gco2e = Column(Float, default=0.0)
    baseline_cost_gco2e = Column(Float, default=0.0)

    # Full flexible routing blob (JSONB on Postgres)
    routing_json = Column(FlexibleJSON, nullable=True)
    knowledge_json = Column(FlexibleJSON, nullable=True)

    # Frequently queried routing metrics (denormalized, indexed)
    selected_model = Column(String(255), nullable=True, index=True)
    crs = Column(Float, nullable=True, index=True)
    confidence = Column(Float, nullable=True, index=True)
    latency_ms = Column(Float, nullable=True, index=True)

    # Phase 2 — object storage metadata (bytes live in R2/S3/local store, not Postgres)
    storage_key = Column(String(512), nullable=True, index=True)
    file_url = Column(String(1024), nullable=True)
    original_filename = Column(String(512), nullable=True)
    content_type = Column(String(128), nullable=True)
    byte_size = Column(Integer, nullable=True)

    user = relationship("UserModel", foreign_keys=[user_id])


class ChunkModel(Base):
    __tablename__ = "chunks"

    id = Column(String(128), primary_key=True, index=True)
    document_id = Column(String(64), index=True)
    chunk_index = Column(String(64))
    text = Column(Text)
    added_at = Column(DateTime(timezone=True), server_default=func.now())
    parent_id = Column(String(128), nullable=True)
    section_path = Column(String(512), nullable=True)
    chunk_kind = Column(String(64), nullable=True)
    token_estimate = Column(Integer, nullable=True)


# ---------------------------------------------------------------------------
# Knowledge graph
# ---------------------------------------------------------------------------


class GraphNodeModel(Base):
    __tablename__ = "graph_nodes"

    id = Column(String(256), primary_key=True)  # {document_id}::{node_id}
    document_id = Column(String(64), index=True, nullable=False)
    node_id = Column(String(128), nullable=False)
    node_type = Column(String(64), nullable=False, default="Entity")
    name = Column(String(512), nullable=False, default="")
    aliases_json = Column(Text, nullable=True)
    evidence_json = Column(Text, nullable=True)


class GraphEdgeModel(Base):
    __tablename__ = "graph_edges"
    __table_args__ = (
        UniqueConstraint("document_id", "src", "rel", "dst", name="uq_graph_edge"),
    )

    id = Column(String(512), primary_key=True)
    document_id = Column(String(64), index=True, nullable=False)
    src = Column(String(128), nullable=False)
    rel = Column(String(128), nullable=False)
    dst = Column(String(128), nullable=False)
    confidence = Column(Float, default=0.5)
    evidence_json = Column(Text, nullable=True)


# ---------------------------------------------------------------------------
# Durable jobs (replaces in-memory JOB_STATUSES when flag enabled)
# ---------------------------------------------------------------------------


class JobModel(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_user_status", "user_id", "status"),
        Index("ix_jobs_queue_claim", "status", "available_at", "created_at"),
    )

    id = Column(String(64), primary_key=True)  # same UUID as document_id / job_id
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String(32), nullable=False, default="pending", index=True)
    progress = Column(Float, default=0.0)
    message = Column(Text, nullable=True)
    understanding = Column(String(32), nullable=True)  # pending|done|failed|skipped
    result_json = Column(JSONType, nullable=True)
    error_detail = Column(Text, nullable=True)
    filename = Column(String(512), nullable=True)
    job_mode = Column(String(64), nullable=True)

    # Indexed routing / quality metrics
    selected_model = Column(String(255), nullable=True, index=True)
    crs = Column(Float, nullable=True, index=True)
    confidence = Column(Float, nullable=True, index=True)
    latency_ms = Column(Float, nullable=True, index=True)
    carbon_saved_grams = Column(Float, nullable=True, index=True)

    # Full routing decision blob
    routing_decision = Column(JSONType, nullable=True)

    # Phase 3 — durable queue claim / retry
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    claimed_by = Column(String(128), nullable=True, index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    available_at = Column(DateTime(timezone=True), nullable=True, index=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)


class WorkerHeartbeatModel(Base):
    """Worker process liveness (Phase 3)."""

    __tablename__ = "worker_heartbeats"

    worker_id = Column(String(128), primary_key=True)
    hostname = Column(String(255), nullable=True)
    status = Column(String(32), nullable=False, default="starting")
    last_seen_at = Column(DateTime(timezone=True), nullable=False, index=True)
    meta_json = Column(JSONType, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------


class ConversationModel(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_document", "document_id"),
        Index("ix_conversations_expires", "expires_at"),
    )

    id = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    document_id = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)

    turns = relationship(
        "ConversationTurnModel",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ConversationTurnModel.ts",
    )


class ConversationTurnModel(Base):
    __tablename__ = "conversation_turns"
    __table_args__ = (
        Index("ix_conversation_turns_conv", "conversation_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(
        String(64),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    entities = Column(JSONType, nullable=True)
    meta = Column(JSONType, nullable=True)
    ts = Column(DateTime(timezone=True), server_default=func.now())

    conversation = relationship("ConversationModel", back_populates="turns")


# ---------------------------------------------------------------------------
# Routing telemetry events
# ---------------------------------------------------------------------------


class RoutingEventModel(Base):
    __tablename__ = "routing_events"
    __table_args__ = (
        Index("ix_routing_events_job", "job_id"),
        Index("ix_routing_events_model_crs", "selected_model", "crs"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(64), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    event_type = Column(String(64), nullable=True, index=True)

    # Indexed metrics
    selected_model = Column(String(255), nullable=True, index=True)
    crs = Column(Float, nullable=True, index=True)
    confidence = Column(Float, nullable=True, index=True)
    latency_ms = Column(Float, nullable=True, index=True)
    carbon = Column(Float, nullable=True, index=True)

    # Full event payload
    event = Column(JSONType, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
