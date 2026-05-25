from __future__ import annotations

from sqlalchemy import Boolean, Engine, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("repo", name="uq_sources_repo"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="github_repo")
    repo: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    filters_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sync_status: Mapped[str] = mapped_column(String(32), nullable=False, default="never")
    last_synced_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False)
    sync_runs: Mapped[list[SourceSyncRun]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
    )
    items: Mapped[list[SourceItem]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
    )


class SourceSyncRun(Base):
    __tablename__ = "source_sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    issue_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pull_request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    started_at: Mapped[str] = mapped_column(String(32), nullable=False)
    completed_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source: Mapped[Source] = relationship(back_populates="sync_runs")


class SourceItem(Base):
    __tablename__ = "source_items"
    __table_args__ = (
        UniqueConstraint("source_id", "kind", "number", name="uq_source_items_identity"),
        Index("ix_source_items_source_kind_state", "source_id", "kind", "state"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    author: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    labels_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    github_updated_at: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    synced_at: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[Source] = relationship(back_populates="items")


def create_model_tables(engine: Engine) -> None:
    Base.metadata.create_all(engine)
