"""add sources table

Revision ID: 0001_sources
Revises:
Create Date: 2026-05-25 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_sources"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "sources" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("repo", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("filters_json", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("sync_status", sa.String(length=32), nullable=False),
        sa.Column("last_synced_at", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.String(length=32), nullable=False),
        sa.Column("updated_at", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("repo", name="uq_sources_repo"),
    )


def downgrade() -> None:
    if "sources" not in sa.inspect(op.get_bind()).get_table_names():
        return
    op.drop_table("sources")
