"""Add durable job-queue claim columns + worker_heartbeats (Phase 3).

Revision ID: 004_job_queue_worker
Revises: 003_document_object_storage
Create Date: 2026-07-10
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "004_job_queue_worker"
down_revision: Union[str, None] = "003_document_object_storage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return name in inspect(op.get_bind()).get_table_names()


def _has_column(table: str, column: str) -> bool:
    if not _has_table(table):
        return False
    return column in {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    cols = [
        ("claimed_at", sa.DateTime(timezone=True)),
        ("claimed_by", sa.String(length=128)),
        ("attempt_count", sa.Integer()),
        ("available_at", sa.DateTime(timezone=True)),
        ("heartbeat_at", sa.DateTime(timezone=True)),
    ]
    with op.batch_alter_table("jobs") as batch:
        for name, typ in cols:
            if not _has_column("jobs", name):
                if name == "attempt_count":
                    batch.add_column(sa.Column(name, typ, nullable=False, server_default="0"))
                else:
                    batch.add_column(sa.Column(name, typ, nullable=True))

    try:
        op.create_index("ix_jobs_claimed_by", "jobs", ["claimed_by"])
    except Exception:
        pass
    try:
        op.create_index("ix_jobs_available_at", "jobs", ["available_at"])
    except Exception:
        pass
    try:
        op.create_index("ix_jobs_queue_claim", "jobs", ["status", "available_at", "created_at"])
    except Exception:
        pass

    if not _has_table("worker_heartbeats"):
        op.create_table(
            "worker_heartbeats",
            sa.Column("worker_id", sa.String(length=128), primary_key=True),
            sa.Column("hostname", sa.String(length=255), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="starting"),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("meta_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_worker_heartbeats_last_seen", "worker_heartbeats", ["last_seen_at"])


def downgrade() -> None:
    if _has_table("worker_heartbeats"):
        op.drop_table("worker_heartbeats")
    for idx in ("ix_jobs_queue_claim", "ix_jobs_available_at", "ix_jobs_claimed_by"):
        try:
            op.drop_index(idx, table_name="jobs")
        except Exception:
            pass
    with op.batch_alter_table("jobs") as batch:
        for name in ("heartbeat_at", "available_at", "attempt_count", "claimed_by", "claimed_at"):
            if _has_column("jobs", name):
                batch.drop_column(name)
