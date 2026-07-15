"""Guest sessions + universal owner columns.

Revision ID: 006_guest_owner
Revises: 005_document_carbon_costs
Create Date: 2026-07-15
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "006_guest_owner"
down_revision: Union[str, None] = "005_document_carbon_costs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return name in inspect(op.get_bind()).get_table_names()


def _has_column(table: str, column: str) -> bool:
    if not _has_table(table):
        return False
    return column in {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def _has_index(table: str, name: str) -> bool:
    if not _has_table(table):
        return False
    return name in {i["name"] for i in inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    if not _has_table("guest_sessions"):
        op.create_table(
            "guest_sessions",
            sa.Column("session_id", sa.String(64), primary_key=True),
            sa.Column("anonymous_name", sa.String(64), nullable=False, server_default="Guest"),
            sa.Column("status", sa.String(32), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_activity", sa.DateTime(timezone=True), nullable=False),
            sa.Column("ip_hash", sa.String(64), nullable=True),
            sa.Column("user_agent_hash", sa.String(64), nullable=True),
            sa.Column("chat_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("upgraded_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        )
        op.create_index("ix_guest_sessions_expires", "guest_sessions", ["expires_at"])
        op.create_index("ix_guest_sessions_status", "guest_sessions", ["status"])

    for table in ("documents", "jobs", "conversations"):
        if not _has_table(table):
            continue
        with op.batch_alter_table(table) as batch:
            if not _has_column(table, "owner_type"):
                batch.add_column(sa.Column("owner_type", sa.String(16), nullable=True))
            if not _has_column(table, "owner_id"):
                batch.add_column(sa.Column("owner_id", sa.String(64), nullable=True))
        if table == "jobs" and not _has_index("jobs", "ix_jobs_owner"):
            op.create_index("ix_jobs_owner", "jobs", ["owner_type", "owner_id"])
        if not _has_index(table, f"ix_{table}_owner_id"):
            try:
                op.create_index(f"ix_{table}_owner_id", table, ["owner_id"])
            except Exception:
                pass

    # Backfill owner_* from user_id where present
    for table in ("documents", "jobs", "conversations"):
        if not _has_table(table) or not _has_column(table, "user_id"):
            continue
        op.execute(
            sa.text(
                f"UPDATE {table} SET owner_type = 'user', owner_id = CAST(user_id AS VARCHAR) "
                f"WHERE user_id IS NOT NULL AND (owner_id IS NULL OR owner_id = '')"
            )
        )


def downgrade() -> None:
    for table in ("conversations", "jobs", "documents"):
        if not _has_table(table):
            continue
        with op.batch_alter_table(table) as batch:
            if _has_column(table, "owner_id"):
                batch.drop_column("owner_id")
            if _has_column(table, "owner_type"):
                batch.drop_column("owner_type")
    if _has_table("guest_sessions"):
        op.drop_table("guest_sessions")
