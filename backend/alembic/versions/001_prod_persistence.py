"""Initial production schema: unified Base + durable runtime tables.

Revision ID: 001_prod_persistence
Revises:
Create Date: 2026-07-10

Backward compatible:
- Creates missing core tables (users, documents, chunks, graph_*)
- Adds nullable columns to documents
- Creates jobs, conversations, conversation_turns, routing_events
- Does not drop or rename existing columns
- JSONB used on PostgreSQL; JSON/TEXT on SQLite
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "001_prod_persistence"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _json_type():
    if _is_postgres():
        return postgresql.JSONB(astext_type=sa.Text())
    return sa.JSON()


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    return name in inspect(bind).get_table_names()


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    if table not in inspect(bind).get_table_names():
        return False
    cols = {c["name"] for c in inspect(bind).get_columns(table)}
    return column in cols


def upgrade() -> None:
    # --- users ---
    if not _has_table("users"):
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("email", sa.String(length=320), nullable=False),
            sa.Column("hashed_password", sa.String(length=255), nullable=False),
            sa.Column("full_name", sa.String(length=255), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1") if not _is_postgres() else sa.text("true")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_users_id", "users", ["id"])
        op.create_index("ix_users_email", "users", ["email"], unique=True)

    # --- documents ---
    if not _has_table("documents"):
        op.create_table(
            "documents",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("saved_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("carbon_saved_grams", sa.Float(), nullable=True),
            sa.Column("processing_time_seconds", sa.Float(), nullable=True),
            sa.Column("total_chunks", sa.Integer(), nullable=True),
            sa.Column("efficiency_percent", sa.Float(), nullable=True),
            sa.Column("routing_json", _json_type(), nullable=True),
            sa.Column("knowledge_json", _json_type(), nullable=True),
            sa.Column("selected_model", sa.String(length=255), nullable=True),
            sa.Column("crs", sa.Float(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("latency_ms", sa.Float(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_documents_id", "documents", ["id"])
        op.create_index("ix_documents_user_id", "documents", ["user_id"])
        op.create_index("ix_documents_selected_model", "documents", ["selected_model"])
        op.create_index("ix_documents_crs", "documents", ["crs"])
        op.create_index("ix_documents_confidence", "documents", ["confidence"])
        op.create_index("ix_documents_latency_ms", "documents", ["latency_ms"])
    else:
        # Additive columns for existing installs
        with op.batch_alter_table("documents") as batch:
            if not _has_column("documents", "user_id"):
                batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
            if not _has_column("documents", "selected_model"):
                batch.add_column(sa.Column("selected_model", sa.String(length=255), nullable=True))
            if not _has_column("documents", "crs"):
                batch.add_column(sa.Column("crs", sa.Float(), nullable=True))
            if not _has_column("documents", "confidence"):
                batch.add_column(sa.Column("confidence", sa.Float(), nullable=True))
            if not _has_column("documents", "latency_ms"):
                batch.add_column(sa.Column("latency_ms", sa.Float(), nullable=True))
            if not _has_column("documents", "routing_json"):
                batch.add_column(sa.Column("routing_json", _json_type(), nullable=True))
            if not _has_column("documents", "knowledge_json"):
                batch.add_column(sa.Column("knowledge_json", _json_type(), nullable=True))
        # Indexes (ignore if exist)
        for name, cols in [
            ("ix_documents_user_id", ["user_id"]),
            ("ix_documents_selected_model", ["selected_model"]),
            ("ix_documents_crs", ["crs"]),
            ("ix_documents_confidence", ["confidence"]),
            ("ix_documents_latency_ms", ["latency_ms"]),
        ]:
            try:
                op.create_index(name, "documents", cols)
            except Exception:
                pass

    # --- chunks ---
    if not _has_table("chunks"):
        op.create_table(
            "chunks",
            sa.Column("id", sa.String(length=128), nullable=False),
            sa.Column("document_id", sa.String(length=64), nullable=True),
            sa.Column("chunk_index", sa.String(length=64), nullable=True),
            sa.Column("text", sa.Text(), nullable=True),
            sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
            sa.Column("parent_id", sa.String(length=128), nullable=True),
            sa.Column("section_path", sa.String(length=512), nullable=True),
            sa.Column("chunk_kind", sa.String(length=64), nullable=True),
            sa.Column("token_estimate", sa.Integer(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_chunks_id", "chunks", ["id"])
        op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    else:
        with op.batch_alter_table("chunks") as batch:
            for col, typ in [
                ("parent_id", sa.String(length=128)),
                ("section_path", sa.String(length=512)),
                ("chunk_kind", sa.String(length=64)),
                ("token_estimate", sa.Integer()),
            ]:
                if not _has_column("chunks", col):
                    batch.add_column(sa.Column(col, typ, nullable=True))

    # --- graph_nodes / graph_edges ---
    if not _has_table("graph_nodes"):
        op.create_table(
            "graph_nodes",
            sa.Column("id", sa.String(length=256), nullable=False),
            sa.Column("document_id", sa.String(length=64), nullable=False),
            sa.Column("node_id", sa.String(length=128), nullable=False),
            sa.Column("node_type", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=512), nullable=False),
            sa.Column("aliases_json", sa.Text(), nullable=True),
            sa.Column("evidence_json", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_graph_nodes_document_id", "graph_nodes", ["document_id"])

    if not _has_table("graph_edges"):
        op.create_table(
            "graph_edges",
            sa.Column("id", sa.String(length=512), nullable=False),
            sa.Column("document_id", sa.String(length=64), nullable=False),
            sa.Column("src", sa.String(length=128), nullable=False),
            sa.Column("rel", sa.String(length=128), nullable=False),
            sa.Column("dst", sa.String(length=128), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("evidence_json", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("document_id", "src", "rel", "dst", name="uq_graph_edge"),
        )
        op.create_index("ix_graph_edges_document_id", "graph_edges", ["document_id"])

    # --- jobs ---
    if not _has_table("jobs"):
        op.create_table(
            "jobs",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("progress", sa.Float(), nullable=True),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("understanding", sa.String(length=32), nullable=True),
            sa.Column("result_json", _json_type(), nullable=True),
            sa.Column("error_detail", sa.Text(), nullable=True),
            sa.Column("filename", sa.String(length=512), nullable=True),
            sa.Column("job_mode", sa.String(length=64), nullable=True),
            sa.Column("selected_model", sa.String(length=255), nullable=True),
            sa.Column("crs", sa.Float(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("latency_ms", sa.Float(), nullable=True),
            sa.Column("carbon_saved_grams", sa.Float(), nullable=True),
            sa.Column("routing_decision", _json_type(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_jobs_user_id", "jobs", ["user_id"])
        op.create_index("ix_jobs_status", "jobs", ["status"])
        op.create_index("ix_jobs_user_status", "jobs", ["user_id", "status"])
        op.create_index("ix_jobs_selected_model", "jobs", ["selected_model"])
        op.create_index("ix_jobs_crs", "jobs", ["crs"])
        op.create_index("ix_jobs_confidence", "jobs", ["confidence"])
        op.create_index("ix_jobs_latency_ms", "jobs", ["latency_ms"])
        op.create_index("ix_jobs_carbon_saved_grams", "jobs", ["carbon_saved_grams"])

    # --- conversations ---
    if not _has_table("conversations"):
        op.create_table(
            "conversations",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("document_id", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
        op.create_index("ix_conversations_document", "conversations", ["document_id"])
        op.create_index("ix_conversations_expires", "conversations", ["expires_at"])

    if not _has_table("conversation_turns"):
        op.create_table(
            "conversation_turns",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("conversation_id", sa.String(length=64), nullable=False),
            sa.Column("role", sa.String(length=16), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("entities", _json_type(), nullable=True),
            sa.Column("meta", _json_type(), nullable=True),
            sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
            sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_conversation_turns_conv", "conversation_turns", ["conversation_id"])

    # --- routing_events ---
    if not _has_table("routing_events"):
        op.create_table(
            "routing_events",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("job_id", sa.String(length=64), nullable=True),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("event_type", sa.String(length=64), nullable=True),
            sa.Column("selected_model", sa.String(length=255), nullable=True),
            sa.Column("crs", sa.Float(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("latency_ms", sa.Float(), nullable=True),
            sa.Column("carbon", sa.Float(), nullable=True),
            sa.Column("event", _json_type(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_routing_events_job", "routing_events", ["job_id"])
        op.create_index("ix_routing_events_job_id", "routing_events", ["job_id"])
        op.create_index("ix_routing_events_user_id", "routing_events", ["user_id"])
        op.create_index("ix_routing_events_event_type", "routing_events", ["event_type"])
        op.create_index("ix_routing_events_selected_model", "routing_events", ["selected_model"])
        op.create_index("ix_routing_events_crs", "routing_events", ["crs"])
        op.create_index("ix_routing_events_confidence", "routing_events", ["confidence"])
        op.create_index("ix_routing_events_latency_ms", "routing_events", ["latency_ms"])
        op.create_index("ix_routing_events_carbon", "routing_events", ["carbon"])
        op.create_index("ix_routing_events_model_crs", "routing_events", ["selected_model", "crs"])


def downgrade() -> None:
    """
    Rollback durable-runtime tables only.
    Does NOT drop users/documents/chunks/graph_* (would destroy app data).
    """
    for table in ("routing_events", "conversation_turns", "conversations", "jobs"):
        if _has_table(table):
            op.drop_table(table)

    # Drop additive document metric columns if present (keep routing_json/knowledge_json)
    if _has_table("documents"):
        with op.batch_alter_table("documents") as batch:
            for col in ("latency_ms", "confidence", "crs", "selected_model", "user_id"):
                if _has_column("documents", col):
                    batch.drop_column(col)
