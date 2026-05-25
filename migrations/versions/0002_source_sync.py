"""add source sync tables

Revision ID: 0002_source_sync
Revises: 0001_sources
Create Date: 2026-05-25 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_source_sync"
down_revision: str | None = "0001_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "source_sync_runs" not in tables:
        op.create_table(
            "source_sync_runs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("source_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("issue_count", sa.Integer(), nullable=False),
            sa.Column("pull_request_count", sa.Integer(), nullable=False),
            sa.Column("error", sa.Text(), nullable=False),
            sa.Column("started_at", sa.String(length=32), nullable=False),
            sa.Column("completed_at", sa.String(length=32), nullable=True),
            sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    if "source_items" not in tables:
        op.create_table(
            "source_items",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("source_id", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(length=32), nullable=False),
            sa.Column("number", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=500), nullable=False),
            sa.Column("url", sa.String(length=500), nullable=False),
            sa.Column("state", sa.String(length=32), nullable=False),
            sa.Column("author", sa.String(length=255), nullable=False),
            sa.Column("labels_json", sa.Text(), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("github_updated_at", sa.String(length=32), nullable=False),
            sa.Column("synced_at", sa.String(length=32), nullable=False),
            sa.Column("created_at", sa.String(length=32), nullable=False),
            sa.Column("updated_at", sa.String(length=32), nullable=False),
            sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("source_id", "kind", "number", name="uq_source_items_identity"),
        )
        op.create_index(
            "ix_source_items_source_kind_state",
            "source_items",
            ["source_id", "kind", "state"],
        )
    elif "ix_source_items_source_kind_state" not in {
        index["name"] for index in sa.inspect(op.get_bind()).get_indexes("source_items")
    }:
        op.create_index(
            "ix_source_items_source_kind_state",
            "source_items",
            ["source_id", "kind", "state"],
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "source_items" in tables:
        op.drop_index("ix_source_items_source_kind_state", table_name="source_items")
        op.drop_table("source_items")
    if "source_sync_runs" in tables:
        op.drop_table("source_sync_runs")
