"""Add document actual/baseline carbon columns for dashboard KPIs.

Revision ID: 005_document_carbon_costs
Revises: 004_job_queue_worker
Create Date: 2026-07-13
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "005_document_carbon_costs"
down_revision: Union[str, None] = "004_job_queue_worker"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return name in inspect(op.get_bind()).get_table_names()


def _has_column(table: str, column: str) -> bool:
    if not _has_table(table):
        return False
    return column in {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if not _has_table("documents"):
        return
    with op.batch_alter_table("documents") as batch:
        if not _has_column("documents", "actual_cost_gco2e"):
            batch.add_column(
                sa.Column("actual_cost_gco2e", sa.Float(), nullable=True, server_default="0")
            )
        if not _has_column("documents", "baseline_cost_gco2e"):
            batch.add_column(
                sa.Column("baseline_cost_gco2e", sa.Float(), nullable=True, server_default="0")
            )


def downgrade() -> None:
    if not _has_table("documents"):
        return
    with op.batch_alter_table("documents") as batch:
        if _has_column("documents", "baseline_cost_gco2e"):
            batch.drop_column("baseline_cost_gco2e")
        if _has_column("documents", "actual_cost_gco2e"):
            batch.drop_column("actual_cost_gco2e")
