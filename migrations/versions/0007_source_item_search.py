"""add source item full text search

Revision ID: 0007_source_item_search
Revises: 0006_work_item_run_runtime_links
Create Date: 2026-05-25 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_source_item_search"
down_revision: str | None = "0006_work_item_run_runtime_links"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    op.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS source_item_search
        USING fts5(source_item_id UNINDEXED, source_id UNINDEXED, title, body)
        """
    )
    if "source_items" not in tables:
        return
    op.execute("DELETE FROM source_item_search")
    op.execute(
        """
        INSERT INTO source_item_search(source_item_id, source_id, title, body)
        SELECT id, source_id, title, body
        FROM source_items
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS source_item_search")
