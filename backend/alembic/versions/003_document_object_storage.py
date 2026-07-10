"""Add document object-storage metadata columns (Phase 2).

Revision ID: 003_document_object_storage
Revises: 002_auth_refresh_tokens
Create Date: 2026-07-10
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "003_document_object_storage"
down_revision: Union[str, None] = "002_auth_refresh_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    if table not in inspect(bind).get_table_names():
        return False
    return column in {c["name"] for c in inspect(bind).get_columns(table)}


def upgrade() -> None:
    cols = [
        ("storage_key", sa.String(length=512)),
        ("file_url", sa.String(length=1024)),
        ("original_filename", sa.String(length=512)),
        ("content_type", sa.String(length=128)),
        ("byte_size", sa.Integer()),
    ]
    with op.batch_alter_table("documents") as batch:
        for name, typ in cols:
            if not _has_column("documents", name):
                batch.add_column(sa.Column(name, typ, nullable=True))
    try:
        op.create_index("ix_documents_storage_key", "documents", ["storage_key"])
    except Exception:
        pass


def downgrade() -> None:
    try:
        op.drop_index("ix_documents_storage_key", table_name="documents")
    except Exception:
        pass
    with op.batch_alter_table("documents") as batch:
        for name in ("byte_size", "content_type", "original_filename", "file_url", "storage_key"):
            if _has_column("documents", name):
                batch.drop_column(name)
