"""add source and work item dispositions

Revision ID: 0005_dispositions
Revises: 0004_source_item_links
Create Date: 2026-05-25 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0005_dispositions"
down_revision: str | None = "0004_source_item_links"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "source_items" in tables:
        _add_column_if_missing(
            inspector, "source_items", sa.Column("disposition", sa.String(32), nullable=True)
        )
        _add_column_if_missing(
            inspector, "source_items", sa.Column("disposition_note", sa.Text(), nullable=True)
        )
        _add_column_if_missing(
            inspector, "source_items", sa.Column("disposition_at", sa.String(32), nullable=True)
        )
        op.execute("UPDATE source_items SET disposition = 'active' WHERE disposition IS NULL")
        op.execute("UPDATE source_items SET disposition_note = '' WHERE disposition_note IS NULL")
    if "work_items" in tables:
        _add_column_if_missing(
            inspector, "work_items", sa.Column("disposition", sa.String(32), nullable=True)
        )
        _add_column_if_missing(
            inspector, "work_items", sa.Column("disposition_note", sa.Text(), nullable=True)
        )
        _add_column_if_missing(
            inspector, "work_items", sa.Column("disposition_at", sa.String(32), nullable=True)
        )
        op.execute("UPDATE work_items SET disposition = 'active' WHERE disposition IS NULL")
        op.execute("UPDATE work_items SET disposition_note = '' WHERE disposition_note IS NULL")


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    for table_name in ("work_items", "source_items"):
        if table_name not in tables:
            continue
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        for column_name in ("disposition_at", "disposition_note", "disposition"):
            if column_name in columns:
                op.drop_column(table_name, column_name)


def _add_column_if_missing(inspector: sa.Inspector, table_name: str, column: sa.Column[Any]) -> None:
    columns = {existing["name"] for existing in inspector.get_columns(table_name)}
    if column.name not in columns:
        op.add_column(table_name, column)
