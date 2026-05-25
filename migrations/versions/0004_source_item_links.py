"""add source item links

Revision ID: 0004_source_item_links
Revises: 0003_work_items
Create Date: 2026-05-25 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_source_item_links"
down_revision: str | None = "0003_work_items"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "work_items" in tables and "active_pr_source_item_id" not in {
        column["name"] for column in inspector.get_columns("work_items")
    }:
        op.add_column("work_items", sa.Column("active_pr_source_item_id", sa.Integer(), nullable=True))
    if "source_item_links" not in tables:
        op.create_table(
            "source_item_links",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("source_id", sa.Integer(), nullable=False),
            sa.Column("source_item_id", sa.Integer(), nullable=False),
            sa.Column("linked_source_item_id", sa.Integer(), nullable=False),
            sa.Column("relationship", sa.String(length=32), nullable=False),
            sa.Column("link_source", sa.String(length=64), nullable=False),
            sa.Column("marker", sa.Text(), nullable=False),
            sa.Column("verified_at", sa.String(length=32), nullable=False),
            sa.ForeignKeyConstraint(["linked_source_item_id"], ["source_items.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_item_id"], ["source_items.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "source_item_id",
                "linked_source_item_id",
                "relationship",
                name="uq_source_item_links_identity",
            ),
        )
        op.create_index("ix_source_item_links_source", "source_item_links", ["source_id"])
        op.create_index("ix_source_item_links_linked", "source_item_links", ["linked_source_item_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "source_item_links" in tables:
        indexes = {index["name"] for index in inspector.get_indexes("source_item_links")}
        if "ix_source_item_links_linked" in indexes:
            op.drop_index("ix_source_item_links_linked", table_name="source_item_links")
        if "ix_source_item_links_source" in indexes:
            op.drop_index("ix_source_item_links_source", table_name="source_item_links")
        op.drop_table("source_item_links")
    if "work_items" in tables and "active_pr_source_item_id" in {
        column["name"] for column in inspector.get_columns("work_items")
    }:
        op.drop_column("work_items", "active_pr_source_item_id")
